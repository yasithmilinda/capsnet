#!/usr/bin/env python

import numpy as np
import tensorflow as tf
from tensorflow.keras import backend as k
from tensorflow.keras import layers, activations, models, utils
from tensorflow.keras.datasets import mnist

# Set random seeds so that the same outputs are generated always
np.random.seed(42)
tf.random.set_seed(42)


def squash(_data, axis=-1):
    squared_norm = k.sum(k.square(_data), axis=axis, keepdims=True)
    squash_factor = squared_norm / (1. + squared_norm)
    unit_vector = _data / k.sqrt(squared_norm + k.epsilon())
    return squash_factor * unit_vector


def safe_l2_norm(_data, axis=-1, keepdims=False):
    squared_norm = k.sum(k.square(_data), axis=axis, keepdims=keepdims)
    return k.sqrt(squared_norm + k.epsilon())


def margin_loss(_y_true, _y_pred, _m_plus=0.9, _m_minus=0.1, _lambda=0.5):
    """
    Loss Function

    :param _y_true: shape: (None, num_caps)
    :param _y_pred: shape: (None, num_caps)
    :param _m_plus: scalar
    :param _m_minus: scalar
    :param _lambda: scalar
    :return: margin loss. shape: (None, )
    """
    present_error = tf.square(tf.maximum(0., _m_plus - _y_pred))
    absent_error = tf.square(tf.maximum(0., _y_pred - _m_minus))
    loss = tf.add(_y_true * present_error, _lambda * (1.0 - _y_true) * absent_error)
    # (None, num_caps)
    _margin_loss = tf.reduce_mean(tf.reduce_sum(loss, axis=1))
    # (None, )
    return _margin_loss


def accuracy(_y_true, _y_pred):
    """

    :param _y_true: shape: (None, num_caps)
    :param _y_pred: shape: (None, num_caps)
    :return:
    """
    _y_pred = tf.argmax(_y_pred, axis=-1)
    _y_true = tf.argmax(_y_true, axis=-1)
    correct = tf.equal(_y_true, _y_pred)
    return tf.reduce_mean(tf.cast(correct, tf.float32))


class DigitCaps(layers.Layer):

    def __init__(self, num_caps, dim_caps, routing_iter, trainable=True, name=None, dtype=None, dynamic=False,
                 **kwargs):
        super().__init__(trainable, name, dtype, dynamic, **kwargs)
        self.num_caps = num_caps
        self.dim_caps = dim_caps
        self.routing_iter = routing_iter
        self.p_num_caps = ...
        self.p_dim_caps = ...
        self.w = ...

    def build(self, input_shape):
        self.p_num_caps = input_shape[-2]
        self.p_dim_caps = input_shape[-1]
        self.w = k.random_normal(shape=(1, self.p_num_caps, self.num_caps, self.dim_caps, self.p_dim_caps), mean=0.0,
                                 stddev=0.1, dtype=tf.float32)
        self.built = True

    @staticmethod
    def apply_routing_weights(_weights, _prediction):
        """
        Weight the prediction by routing weights, squash it, and return it

        :param _weights: (batch_size, p_num_caps, num_caps, 1, 1)
        :param _prediction: (batch_size, p_num_caps, num_caps, dim_caps, 1)
        :return:
        """
        # softmax of weights over num_caps axis
        softmax_routing = k.softmax(_weights, axis=2)
        '''shape: (batch_size, p_num_caps, num_caps, 1, 1)'''

        # elementwise multiplication of weights with prediction
        w_prediction = tf.multiply(softmax_routing, _prediction)
        '''shape: (batch_size, p_num_caps, num_caps, dim_caps, 1)'''

        # sum over p_num_caps axis
        w_prediction_sum = k.sum(w_prediction, axis=1, keepdims=True)
        '''shape: (batch_size, 1, num_caps, dim_caps, 1)'''

        squashed_w_prediction_sum = squash(w_prediction_sum, axis=-2)
        '''shape: (batch_size, 1, num_caps, dim_caps, 1)'''

        return squashed_w_prediction_sum

    def call(self, inputs, **kwargs):
        # get batch size of input
        batch_size = k.shape(inputs)[0]
        # reshape input
        batch_input = k.expand_dims(inputs, axis=-1)
        '''shape: (batch_size, p_num_caps, p_dim_caps, 1)'''
        batch_input = k.expand_dims(batch_input, axis=2)
        '''shape: (batch_size, p_num_caps, 1, p_dim_caps, 1)'''
        batch_input = k.tile(batch_input, [1, 1, self.num_caps, 1, 1])
        '''shape: (batch_size, p_num_caps, num_caps, p_dim_caps, 1)'''

        # tile transformation matrix for each element in batch
        batch_w = k.tile(self.w, [batch_size, 1, 1, 1, 1])
        '''shape: (batch_size, p_num_caps, num_caps, dim_caps, p_dim_caps)'''

        # calculate prediction (dot product of batch_w and batch_input)
        # this returns the matrix multiplication of last two dims, preserving previous dims
        prediction = tf.matmul(batch_w, batch_input)
        '''shape: (batch_size, p_num_caps, num_caps, dim_caps, 1)'''

        # ROUTING SECTION ----------
        # initialize routing weights to zero
        routing_weights = tf.zeros(shape=(batch_size, self.p_num_caps, self.num_caps, 1, 1), dtype=tf.float32)
        '''shape: (batch_size, p_num_caps, num_caps, 1, 1)'''

        @tf.function
        def dynamic_routing(w_routing):
            # update routing weights for routing_iter iterations
            for i in range(self.routing_iter):
                # step 1: getting weighted prediction
                w_prediction = self.apply_routing_weights(w_routing, prediction)
                '''shape: (batch_size, 1, num_caps, dim_caps, 1)'''
                # step 2: tile the weighted prediction for each previous capsule
                w_prediction_tiled = k.tile(w_prediction, [1, self.p_num_caps, 1, 1, 1])
                '''shape: (batch_size, p_num_caps, num_caps, dim_caps, 1)'''
                # step 3: find the agreement between prediction and weighted prediction
                agreement = tf.matmul(prediction, w_prediction_tiled, transpose_a=True)
                '''shape: (batch_size, p_num_caps, num_caps, 1, 1)'''
                # update routing weights based on agreement
                w_routing = tf.add(w_routing, agreement)
            # return the final prediction after routing
            w_prediction = self.apply_routing_weights(w_routing, prediction)
            '''shape: (batch_size, 1, num_caps, dim_caps, 1)'''
            return w_prediction

        final_prediction = dynamic_routing(routing_weights)

        # reshape to (None, num_caps, dim_caps)
        return tf.reshape(final_prediction, shape=(-1, self.num_caps, self.dim_caps))


if __name__ == '__main__':
    (x_train, y_train), (x_test, y_test) = mnist.load_data()

    x_train = x_train / 255.0
    x_test = x_test / 255.0

    x_train, x_test = x_train[..., np.newaxis], x_test[..., np.newaxis]
    NUM_CLASSES = 10
    y_train, y_test = utils.to_categorical(y_train, NUM_CLASSES), utils.to_categorical(y_test, NUM_CLASSES)

    _input_shape = x_train.shape[1:]
    _output_shape = y_train.shape[1:]

    # CAPSULE NETWORK ARCHITECTURE ---
    conv_1_spec = {
        'filters': 256,
        'kernel_size': (9, 9),
        'strides': (1, 1),
        'activation': activations.relu
    }

    # capsule 1 spec
    num_filters = 32
    dim_cap_1 = 8

    conv_2_spec = {
        'filters': num_filters,
        'kernel_size': (9, 9),
        'strides': (2, 2),
        'activation': activations.relu
    }

    digit_caps_spec = {
        'num_caps': 10,
        'dim_caps': 16,
        'routing_iter': 3
    }

    # input
    l1 = layers.Input(shape=_input_shape)

    # initial convolution
    l2 = layers.Conv2D(**conv_1_spec)(l1)

    # primary caps (convolution + reshape + squash)
    l3 = layers.Conv2D(**conv_2_spec)(l2)
    l4 = layers.Reshape((np.prod(l3.shape[1:]) // dim_cap_1, dim_cap_1))(l3)
    l5 = layers.Lambda(squash)(l4)

    # digit caps (routing based on agreement -> weighted prediction)
    l6 = DigitCaps(**digit_caps_spec)(l5)

    # predictions (None, dim_caps)
    l7 = layers.Lambda(safe_l2_norm)(l6)

    # define the model
    model = models.Model(inputs=l1, outputs=[l7], name='capsule_network')
    model.compile(optimizer='adam', loss=[margin_loss], metrics=[accuracy])

    # training
    model.fit(x_train, y_train, batch_size=50, epochs=2, validation_split=0.1)

    # evaluation
    model.evaluate(x_test, y_test)