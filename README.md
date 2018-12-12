# Deep Watershed Detection
This repository holds the code to train and evaluate DWD models.
The documentation is intended enable easy use of the code, for an explanation of the
methods please refer to the original publication.

#### Installation
The code is tested on python version 3.6 and Tensorflow 1.4.1, to install dependencies run inside the repo base directory (`repo_home`):
`pip install -r requirements.txt`. The image database module taken from the original [fast r-cnn repository](https://github.com/rbgirshick/fast-rcnn) and it has some cython code that needs to be compiled by running `make all` inside lib.

#### Data
As it is, the path for the data should be:

```/DeepWatershedDetection/data/DeepScores_2017``` for DeepScores.

```/DeepWatershedDetection/data/DeepScores_300dpi_2017``` for the scanned version of DeepScores.

```/DeepWatershedDetection/data/DeepScores_ipad_2017``` for the ipad version of DeepScores.

```/DeepWatershedDetection/data/MUSICMA++_2017``` for MUSCIMA++ dataset.

```/DeepWatershedDetection/data/your_data_set``` for some other dataset you might want to use.

All three DeepScores dataset have the same structure. We will explain the structure of DeepScores_2017, but you can generalize for the other datasets. The directory has the following structure:

```annotations_cache``` - create it using mkdir ```/DeepWatershedDetection/data/DeepScores_2017/annotations_cache```.

```DeepScores_classification``` - contains a single file named ```class_names.csv``` which maps names of musical symbol classes to numbers.

```results``` - contains a folder called ```musical2017``` which contains a folder called ```Main``` needed for internal procedures during training. Please create the folders using mkdir. The path should be ```/DeepWatershedDetection/data/DeepScores_2017/results/musical2017/Main```.

```segmentation_detection``` - contains the dataset with the following structure:
         
         ```images_png``` - all images of the data set, in png format.
         
         ```pix_annotations_png``` - pixelwise annotations in png format, at the moment is not used, however we plan to use it in the future as an improvement for out model.
         
         ```xml_annotations``` - the ground truth for the detection, xml format.
         
The names of an image, its corresponding ground truth, and its corresponding pixelwise annotation must be the same. For example, image ```lg-527907832922209940-aug-beethoven--page-5.png``` located in ```images_png``` must have a corresponding   ```lg-527907832922209940-aug-beethoven--page-5.xml``` located in ```xml_annotations``` and might have (optionally) a ```lg-527907832922209940-aug-beethoven--page-5.png``` located in ```pix_annotations_png```.

```train_val_test``` contains 3 files called train.txt, val.txt and test.txt which have the names of images for training, validation and testing set.

NB: For hyperparameter optimization, we have merged val.txt and test.txt in order to have a validation set which has a higher representation of different classes. For an unbiased evaluation, it is highly recommended to get a new fresh test set and do a single evaluation there (with the best model we have). priority - high.


MUSICMA++ has a similar structure, with the following difference:

         ```MUSICMA++_2017``` - replaces ```segmentation_detection``` and has the exact structure.
         
The full dataset can be downloaded [here](https://tuggeluk.github.io/downloads/). For Pascal VOC data
please refer to the [official website](http://host.robots.ox.ac.uk/pascal/VOC/).

#### Model Training
To train a DWD model DeepScores_dense run:
```
cd repo_home/lib
python main/train.py
```
`train.py` contains a variety of configuration possibilities, most of them are easily understood
from the help. Some of the most important ones are explained here:

+ Dataset

```dataset = "DeepScores_2017_train"``` tells the classifier which dataset to use for training. Options are ```DeepScores_2017_train``` for DeepScores, ```DeepScores_300dpi_2017_train``` for the scanned version of DeepScores, ```DeepScores_ipad_2017_train``` for the ipad version of DeepScores, ```MUSICMA++_2017_train``` for the handwritten dataset.

+ Input Scaling

```scale_list``` - we have set it to 0.5 in all experiments.

+ Pretraining

```pretrain_lvl``` - the net performs better if it is pretrained in some other task. For DeepScores, we first pretrained the net in semantic segmentation task (option: ```semseg```), for scanned version of DeepScores, we do finetuning of a net already trained on DeepScores (option: ```DeepScores_300dpi_2017_train```).

+ Definition of training assignments

We do the training in stages, as explained in ISMIR paper. You can set the number of iterations for each task in ```Itrs0, Itrs1, Itrs2, Itrs0_1, Itrs_combined```. For the best results we have so far, we use ```Itrs0, Itrs1, Itrs2, Itrs0_1, Itrs_combined = 20000, 20000, 20000, 10000, 30000```

+ Augmentation with synthetic symbols

Field ```augmentation_type``` sets the synthetic augmentation as described on ANNPR and WORMS papers. By default is set to ```no``` which means no synthetic augmentation. You can set this field to ```up``` which augments 12 synthetic images above the sheet, or ```full``` which creates a page totally synthetized. Augmentation might be considered in cases where the dataset is very unbalanced.

+ Base model

Field ```model``` is set by default to ```RefineNet-Res101```, however you can change the model of ResNet to other ResNets.We used for experiments always ResNet101, however ResNet152 should work slightly better (and make both training and inference slower).

+ Other important training parameters

We did a random hyperparameter search for learning rate and l2 regularization coefficient. The exact values for these hyperparameters can be seen in the folders for each net, however we found that training works well if learning rate is set close to 5e-5, while l2 is set close to 5e-7. For optimizer we have used rmsprop, however, the code accepts also Adam and SGD with momentum.


#### Saving Nets

Nets are saved by default in a path looking like: ```/DeepWatershedDetection/experiments/music/<pretrain level>/<net model>/<net id>```. For example a net trained on DeepScores will be saved on the path: ```/DeepWatershedDetection/experiments/music/pretrain_lvl_semseg/RefineNet-Res101/run_0``` where ```run_0, run_1, run_2, ..., run_n``` etc are created automatically for each new run of training. For ```DeepScores_300dpi``` (scans) replace ```pretrain_lvl_semseg``` with ```pretrain_lvl_DeepScores_to_300dpi```, and for the version ```DeepScores_ipad``` (photos) with ```pretrain_lvl_DeepScores_to_ipad```. For MUSCIMA, the path would be ```/DeepWatershedDetection/experiments/music_handwritten/pretrain_lvl_semseg/RefineNet-Res101/run_0```.

On each folder where a net is saved, you will find the following files:

         Files which have the serialized net, can be used for predictions and/or further training of that net:
         
                  backbone.data-00000-of-00001
                  backbone.meta
                  backbone.index
                  checkpoint
                  
         dict.pickle - a dictionary saved on pickle format which saves information about how the net was trained (number of iterations, optimizer used, augmentation type, learning rate, l2 parameter etc).
         
         events.out.tfevents - tensorboard file
         
         res-0.5.txt - Average precision in validation set at IoU = 0.5
         res-0.55.txt - Average precision in validation set at IoU = 0.55
         ...
         res-0.95.txt - Average precision in validation set at IoU = 0.95


#### Model Evaluation
In order to evaluate a model run:

cd DeepWatershedDetection/lib/main
python inference.py

On the main method, give the path of the model we are using to evaluate


#### Recent changes
- a large part of the code is cleaned, made more human readable and partially optimized.
- implements data augmentation (see WORMS paper from Elezi, Tugginer, Pelillo and Stadelmann).
- implements l2-regularization.
- implements random search for hyperparameter optimization.
- in addition to rmsprop, the nets now can be trained using adam and sgd with momentum (we have done hyperparameter optimization only using rmsprop)
- implements focal loss (it has been tested that it works, but no hyperparameter optimization has been done).
- you do not need to track the information on hyperparameters and results, all the needed information is stored on the same folder where is the net.
- run.sh allows sequential running.
- a lot of visualization code, for both debugging and testing purposes
