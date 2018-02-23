
import os
import tensorflow as tf
import numpy as np
import argparse
import sys
from main.config import cfg

from models.dwd_net import build_dwd_net

from datasets.factory import get_imdb
from tensorflow.contrib import slim
from main.dws_transform import perform_dws
from utils.safe_softmax_wrapper import safe_softmax_cross_entropy_with_logits
import roi_data_layer.roidb as rdl_roidb
from roi_data_layer.layer import RoIDataLayer
import utils.summary_helpers as sh
from collections import OrderedDict
from utils.prefetch_wrapper import PrefetchWrapper

from PIL import Image, ImageDraw

# Training regime
# - make different FCN architecture available --> RefineNet, DeepLabv3, standard fcn
# - pretrain on classification i.e. make classification loss available
#
# - try high dimensional loss
# - try regression loss
# - with and without pretraining on semantic segmentation


def main(unused_argv):
    print(args)

    np.random.seed(cfg.RNG_SEED)

    # load databases
    print("Setting up image database: " + args.dataset)
    imdb = get_imdb(args.dataset)
    print('Loaded dataset `{:s}` for training'.format(imdb.name))
    roidb = get_training_roidb(imdb, args.use_flipped == "True")
    print('{:d} roidb entries'.format(len(roidb)))

    if args.dataset_validation != "no":
        print("Setting up validation image database: " + args.dataset_validation)
        imdb_val = get_imdb(args.dataset_validation)
        print('Loaded dataset `{:s}` for validation'.format(imdb_val.name))
        roidb_val = get_training_roidb(imdb_val, False)
        print('{:d} roidb entries'.format(len(roidb_val)))
    else:
        imdb_val = None
        roidb_val = None


    data_layer = RoIDataLayer(roidb, imdb.num_classes)

    if roidb_val is not None:
        data_layer_val = RoIDataLayer(roidb_val, imdb_val.num_classes, random=True)

    if args.prefetch == "True":
        data_layer_pw = PrefetchWrapper(data_layer.forward, args.prefetch_len, args)

    batch_not_loaded = True
    while batch_not_loaded:
        data = data_layer.forward(args)
        batch_not_loaded = len(data["gt_boxes"].shape) != 3
    # dws_list = perform_dws(data["dws_energy"], data["class_map"], data["bbox_fcn"])

    # tensorflow session
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.Session(config=config)

    # input and output tensors
    num_classes = len(imdb._classes)

    if "DeepScores" in args.dataset:
        input = tf.placeholder(tf.float32, shape=[None, None, None, 1])
        img_pred_placeholder = tf.placeholder(tf.uint8, shape=[1, None, None, 1])
        resnet_dir = cfg.PRETRAINED_DIR+"/DeepScores/"
        refinenet_dir = cfg.PRETRAINED_DIR+"/DeepScores_semseg/"
        image_mode = "music"

    else:
        input = tf.placeholder(tf.float32, shape=[None, None, None, 3])
        img_pred_placeholder = tf.placeholder(tf.uint8, shape=[1, None, None, 3])
        resnet_dir = cfg.PRETRAINED_DIR+"/ImageNet/"
        refinenet_dir = cfg.PRETRAINED_DIR+"/VOC2012/"
        image_mode = "realistic"

    # label placeholders
    # dws_labels
    label_dws_energy = tf.placeholder(tf.float32, shape=[None, None, None, 1])
    label_class = tf.placeholder(tf.float32, shape=[None,  None, None, num_classes])
    label_bbox = tf.placeholder(tf.float32, shape=[None, None, None, 2])
    label_foreground = tf.placeholder(tf.float32, shape=[None, None, None, 2])

    # original bbox label
    label_orig = tf.placeholder(tf.float32, shape=[None, None, 5])

    img_energy_placeholder = tf.placeholder(tf.uint8, shape=[1, None, None, 1])

    print("Initializing Model:" + args.model)
    [foreground, dws_energy, class_logits, bbox_size],init_fn = build_dwd_net(
        input, model=args.model,num_classes=num_classes, pretrained_dir=resnet_dir, substract_mean=False)

    with tf.variable_scope('deep_watershed'):
        print("Using loss:")
        # Hack foreground loss
        #energy_loss = tf.reduce_mean(tf.losses.mean_squared_error(predictions=dws_energy, labels=label_dws_energy))
        energy_loss = tf.reduce_mean(safe_softmax_cross_entropy_with_logits(logits=foreground, labels=label_foreground))


        dws_mask = tf.squeeze(label_dws_energy >= 0, -1)

        class_masked_logits = tf.boolean_mask(class_logits, dws_mask)
        class_masked_labels = tf.boolean_mask(label_class, dws_mask)
        class_loss = tf.reduce_mean(safe_softmax_cross_entropy_with_logits(logits=class_masked_logits, labels=class_masked_labels))

        bbox_masked_predictions = tf.boolean_mask(bbox_size, dws_mask)
        class_masked_labels = tf.boolean_mask(label_bbox, dws_mask)
        box_loss = tf.reduce_mean(tf.losses.mean_squared_error(predictions=bbox_masked_predictions, labels=class_masked_labels))

        ec_loss = tf.add(energy_loss * 1.0, class_loss * 0.5)
        tot_loss = tf.add(ec_loss * 1.0, box_loss * 0.5)


        print("Init optimizers")
        var_list = [var for var in tf.trainable_variables()]
        opt_energy = tf.train.RMSPropOptimizer(learning_rate=0.0001, decay=0.995).minimize(energy_loss, var_list=var_list)
        # opt_ec = tf.train.RMSPropOptimizer(learning_rate=0.0001, decay=0.995).minimize(ec_loss, var_list=var_list)
        #opt_tot = tf.train.RMSPropOptimizer(learning_rate=0.0001, decay=0.995).minimize(tot_loss, var_list=var_list)

        print("Init Summary")
        scalar_sums = []
        scalar_sums.append(tf.summary.scalar("energy_loss", energy_loss))
        scalar_sums.append(tf.summary.scalar("class_loss", class_loss))
        scalar_sums.append(tf.summary.scalar("box_loss", box_loss))
        scalar_sums.append(tf.summary.scalar("tot_loss", tot_loss))
        scalar_summary_op = tf.summary.merge(scalar_sums)

        images_sums = []
        images_sums.append(tf.summary.image('Energy_Map', img_energy_placeholder))
        images_sums.append(tf.summary.image('Prediction', img_pred_placeholder))
        images_summary_op = tf.summary.merge(images_sums)



    saver = tf.train.Saver(max_to_keep=1000)
    sess.run(tf.global_variables_initializer())

    # set up saver path
    checkpoint_dir = cfg.EXP_DIR + "/" + image_mode
    checkpoint_name =  args.model
    if args.continue_training == "True":
        print("Loading checkpoint")
        saver.restore(sess, checkpoint_dir + "/" + checkpoint_name)
    else:
        if args.pretrain_lvl == "semseg":
            #load all variables except the ones in scope "deep_watershed"
            pretrained_vars = []
            for var in slim.get_model_variables():
                if "deep_watershed" not in var.name:
                    pretrained_vars.append(var)

            print("Loading network pretrained on semantic segmentation")
            loading_checkpoint_name = refinenet_dir + args.model + ".ckpt"
            init_fn = slim.assign_from_checkpoint_fn(loading_checkpoint_name, pretrained_vars)
            init_fn(sess)
        elif args.pretrain_lvl == "class":
            print("Loading pretrained weights for level: " + args.pretrain_lvl)
            init_fn(sess)
        else:
            print("Not loading a pretrained network")

    # set up tensorboard
    tbdir = cfg.EXP_DIR + "/" + image_mode + "/" + args.model+"_tensorboard"
    writer = tf.summary.FileWriter(tbdir, sess.graph)

    print("Start training")
    for itr in range(1, 50000):
        # load batch - only use batches with content
        batch_not_loaded = True
        while batch_not_loaded:
            if args.prefetch == "True":
                blob = data_layer_pw.get_item()
            else:
                blob = data_layer.forward(args)
            batch_not_loaded = len(blob["gt_boxes"].shape) != 3


        if "DeepScores" in args.dataset:
            blob["data"] = np.expand_dims(np.mean(blob["data"], -1), -1)
            #one-hot class labels
            blob["class_map"] = np.eye(imdb.num_classes)[blob["class_map"][:, :, :, -1]]

        if "voc" in args.dataset:
            #one-hot class labels
            blob["class_map"] = np.eye(imdb.num_classes)[blob["class_map"][:, :, :, -1]]
            blob["foreground"] = np.eye(2)[blob["foreground"][:, :, :, -1]]


        # train step
        _, energy_loss_fetch, class_loss_fetch, box_loss_fetch = sess.run([opt_energy, energy_loss,class_loss,box_loss],
                                                        feed_dict={input: blob["data"],
                                                                   label_dws_energy: blob["dws_energy"],
                                                                   label_class: blob["class_map"],
                                                                   label_bbox: blob["bbox_fcn"],
                                                                   label_orig: blob["gt_boxes"],
                                                                   label_foreground: blob["foreground"]})

        if itr % args.save_interval == 0 or itr == 1:
            _, summary, energy_loss_fetch, class_loss_fetch, box_loss_fetch, pred_energy, pred_foreground, pred_class_logits, pred_bbox = sess.run(
                [opt_energy, scalar_summary_op, energy_loss, class_loss, box_loss, dws_energy,foreground, class_logits, bbox_size],
                feed_dict={input: blob["data"],
                           label_dws_energy: blob["dws_energy"],
                           label_class: blob["class_map"],
                           label_bbox: blob["bbox_fcn"],
                           label_orig: blob["gt_boxes"],
                           label_foreground: blob["foreground"]})


            writer.add_summary(summary, float(itr))
            print("add-prediciton to tensorboard")
            # compute prediction
            pred_class = np.argmax(pred_class_logits, axis=3)
            dws_list = perform_dws(pred_energy, pred_class, pred_bbox)

            # build images
            # rescale
            # pred_scaled = pred_foreground[0] + np.abs(np.min(pred_foreground[0]))
            # pred_scaled = pred_scaled / np.max(pred_scaled)*255
            # np.argmax(, axis=None, out=None)
            pred_scaled = np.argmax(pred_foreground[0], axis=-1, out=None)
            pred_scaled = np.expand_dims(pred_scaled, -1)*255

            orig_scaled = np.argmax(blob["foreground"][0], axis=-1, out=None)
            orig_scaled = np.expand_dims(orig_scaled, -1)*255

            conc_array = np.concatenate((pred_scaled, orig_scaled), 0)
            energy_array = np.squeeze(conc_array.astype("uint8"))
            energy_array = np.expand_dims(np.expand_dims(energy_array, -1), 0)

            # switch bgr to rgb
            im_rgb = blob["data"][0][:,:,[2,1,0]]+cfg.PIXEL_MEANS[:,:,[2,1,0]]
            im = Image.fromarray(im_rgb.astype("uint8"))
            draw = ImageDraw.Draw(im)
            # overlay GT boxes
            for row in blob["gt_boxes"][0]:
                draw.rectangle(((row[0], row[1]), (row[2], row[3])), outline="green")
            for row in dws_list:
                draw.rectangle(((row[0], row[1]), (row[2], row[3])), outline="red")
            im_array = np.array(im).astype("uint8")
            im_array = np.expand_dims(im_array, 0)

            if len(im_array.shape) < 4:
                im_array = np.expand_dims(im_array, -1)


            # save images to tensorboard
            summary = sess.run([images_summary_op],
                     feed_dict={
                         img_pred_placeholder: im_array,
                         img_energy_placeholder: energy_array})
            writer.add_summary(summary[0], float(itr))

            print("loss at itr: " + str(itr))
            print("energy_loss: " + str(energy_loss_fetch))
            print("class_loss: " + str(class_loss_fetch))
            print("box_loss: " + str(box_loss_fetch))



        if itr % args.save_interval == 0:
            print("saving weights")
            if not os.path.exists(checkpoint_dir):
                os.makedirs(checkpoint_dir)
            saver.save(sess, checkpoint_dir + "/" + checkpoint_name)


def train_on_task(itr,end_itr,task):
    print("")


def get_training_roidb(imdb, use_flipped):
  """Returns a roidb (Region of Interest database) for use in training."""
  if use_flipped:
    print('Appending horizontally-flipped training examples...')
    imdb.append_flipped_images()
    print('done')

  print('Preparing training data...')
  rdl_roidb.prepare_roidb(imdb)
  print('done')

  return imdb.roidb




if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("--scale_list", type=list, default=[0.9,1,1.1], help="global scaling factor randomly chosen from this list")
    parser.add_argument("--crop", type=str, default="False", help="should images be cropped")
    parser.add_argument("--crop_size", type=bytearray, default=[640,640], help="size of the image to be cropped to")
    parser.add_argument("--crop_top_left_bias", type=float, default=0.3, help="fixed probability that the crop will be from the top left corner")
    parser.add_argument("--max_edge", type=int, default=1280, help="if there is no cropping - scale such that the longest edge has this size")
    parser.add_argument("--use_flipped", type=str, default="False", help="wether or not to append Horizontally flipped images")
    parser.add_argument("--substract_mean", type=str, default="True", help="wether or not to substract the mean of the VOC images")
    parser.add_argument("--pad_to", type=int, default=320, help="pad the final image to have edge lengths that are a multiple of this - use 0 to do nothing")
    parser.add_argument("--pad_with", type=int, default=0,help="use this number to pad images")

    parser.add_argument("--prefetch", type=str, default="False", help="use additional process to fetch batches")
    parser.add_argument("--prefetch_len", type=int, default=2, help="prefetch queue len")

    parser.add_argument("--batch_size", type=int, default=1, help="batch size for training") # code only works with batchsize 1!
    parser.add_argument("--continue_training", type=str, default="False", help="load checkpoint")
    parser.add_argument("--pretrain_lvl", type=str, default="semseg", help="What kind of pretraining to use: no,class,semseg")
    parser.add_argument("--learning_rate", type=float, default=1e-4, help="Learning rate for Adam Optimizer")
    parser.add_argument("--dataset", type=str, default="voc_2012_train", help="DeepScores, voc or coco")
    parser.add_argument("--dataset_validation", type=str, default="DeepScores_2017_debug", help="DeepScores, voc, coco or no - validation set")
    parser.add_argument("--tensorboard_interval", type=int, default=100, help="after how many iterations is tensorboard updated")
    parser.add_argument("--save_interval", type=int, default=2000, help="after how many iterations are the weights saved")


    parser.add_argument('--model', type=str, default="RefineNet-Res101", help="Base model -  Currently supports: RefineNet-Res50, RefineNet-Res101, RefineNet-Res152")
    parser.add_argument('--training_regime', type=OrderedDict, default={'pre_energy1': '2000', 'energy': '1000', 'tot': '4'}, help="Training regime: how many iterations are to be trained on which loss")


    args, unparsed = parser.parse_known_args()
    tf.app.run(main=main, argv=[sys.argv[0]] + unparsed)