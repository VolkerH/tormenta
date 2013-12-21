# -*- coding: utf-8 -*-
"""
Created on Fri Dec 13 17:36:09 2013

@author: fbaraba
"""

import os

import numpy as np
import h5py as hdf


def store_stack(file_name, data, attributes=None):
    """Store binary data and measurement attributes in HDF5 format"""

    store_file = hdf.File(file_name + '.hdf5', "w")

    # data should be a list of tuples in the format ('data name', data)
    if type(data) == tuple:
        data = [data]

    for i in np.arange(len(data)):
        store_file.create_dataset(data[i][0], data=data[i][1])

    if attributes is None:
        print("No attributes were saved")

    else:
        for i in np.arange(len(attributes)):
            store_file.attrs[attributes[i][0]] = attributes[i][1]

    store_file.close()

if __name__ == "__main__":

    import tkFileDialog as filedialog
    from Tkinter import Tk

    root = Tk()
    filename = filedialog.askopenfilename(parent=root,
                                          title='Select file to be packed')
    root.destroy()

    shape = (1363, 185, 197)

    data = np.memmap(filename, dtype=np.dtype('uint16'), mode='r')
    data = data.reshape(shape)

    file_name = os.path.splitext(filename)
    attributes = [('nframes', shape[0]), ('size', shape[1:3])]
    data_name = 'frames'

    store_stack(file_name[0], (data_name, data), attributes)
