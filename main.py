#!/usr/bin/env python3
import os
import sys

import numpy as np
import tensorflow as tf
from tensorflow import keras as k
from tensorflow.keras.datasets import mnist, cifar10, cifar100

from capsnet import losses
from functions import print_results
from models import get_model

# configuration
BASE_PATH = ""

# error messages
USAGE_EXPR = '''Usage:
    ./main  [ [MODE] train | test | demo ]
            [ [Dataset] mnist | cifar10 | cifar100 ]
            [ [MODEL NAME] original | deepcaps ]
'''
ERR_FILE_NOT_FOUND = "file not found"

if __name__ == '__main__':
    # command-line arguments
    assert len(sys.argv) == 4, USAGE_EXPR
    mode = sys.argv[1].strip().lower()
    dataset_name = sys.argv[2].strip().lower()
    model_name = sys.argv[3].strip().lower()
    assert mode in ["train", "test", "demo"], USAGE_EXPR
    assert dataset_name in ["mnist", "cifar10", "cifar100"], USAGE_EXPR
    assert model_name in ["original", "deepcaps"], USAGE_EXPR

    # set random seeds
    np.random.seed(42)
    tf.random.set_seed(42)

    # load data
    if dataset_name == "mnist": dataset = mnist
    if dataset_name == "cifar10": dataset = cifar10
    if dataset_name == "cifar100": dataset = cifar100

    (x_train, y_train), (x_test, y_test) = dataset.load_data()
    NUM_CLASSES = len(np.unique(y_train))

    # transform data for training
    if len(x_train.shape) == 3:
        x_train, x_test = x_train[..., None], x_test[..., None]
    if len(y_train.shape) == 1:
        y_train, y_test = y_train[..., None], y_test[..., None]
    # prepare for training
    x_train = tf.divide(x_train, 255.0)
    x_test = tf.divide(x_test, 255.0)
    y_train = tf.one_hot(y_train.astype(int), NUM_CLASSES, axis=-1)
    y_test = tf.one_hot(y_test.astype(int), NUM_CLASSES, axis=-1)

    # configure model and print summary
    model = get_model(name=model_name, input_shape=x_train.shape[1:], num_classes=NUM_CLASSES)
    model.compile(optimizer='adam',
                  loss=[losses.margin_loss, 'mse'],
                  loss_weights=[1, 5e-3],
                  metrics={'pred': 'acc'})
    model.summary(line_length=150)

    filepath = f"{BASE_PATH}weights_{model_name}_{dataset_name}.hdf5"

    if mode == "train":
        checkpoint = k.callbacks.ModelCheckpoint(filepath, save_best_only=True)
        model.fit(x_train, [y_train, x_train],
                  batch_size=50,
                  epochs=5,
                  validation_split=0.1,
                  use_multiprocessing=True,
                  workers=2,
                  callbacks=[checkpoint])

    if mode == "test":
        assert os.path.exists(filepath), ERR_FILE_NOT_FOUND
        model.load_weights(filepath)
        model.evaluate(x_test, [y_test, x_test])

    if mode == "demo":
        assert os.path.exists(filepath), ERR_FILE_NOT_FOUND
        model.load_weights(filepath)
        [y_pred, x_pred] = model.predict(x_test)
        print_results(x_test, x_pred, y_test, y_pred, samples=20, cols=5)
