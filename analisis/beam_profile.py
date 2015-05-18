# -*- coding: utf-8 -*-
"""
Created on Mon Apr 14 19:19:37 2014
Created on Wed May 13 23:35:23 2015

@author: federico
"""

import numpy as np
from tkinter import Tk, filedialog

from stack import Stack


def loadStacks():
    # Get filenames from user
    try:
        root = Tk()
        stacksNames = filedialog.askopenfilenames(parent=root)
        root.destroy()
    except OSError:
        print("No files selected!")

    return stacksNames


def beamProfile(shape=(512, 512)):

    profile = np.zeros(shape)

    for filename in loadStacks():
        stack = Stack(filename=filename)
        meanFrame = stack.imageData.mean(0)
        profile += meanFrame / meanFrame.mean()
        stack.close()

    return profile


#def analyze_beam(epinames=None, tirfnames=None):
#
#    if epinames is None:
#        epinames = load_files('epi')
#        tirfnames = load_files('tirf')
#
#    epi_mean = beam_mean(epinames)
#    tirf_mean = beam_mean(tirfnames)
#
#    tirf_factor = frame(tirf_mean).mean() / frame(epi_mean).mean()
#    frame_factor = frame(tirf_mean).mean() / tirf_mean.mean()
#    variance = 100 * frame(tirf_mean).std() / frame(tirf_mean).mean()
#
#    return tirf_factor, frame_factor, variance
#
#if __name__ == "__main__":
#
#    epi_fov = beam_mean(bp.load_files('epi'))
#    tirf_fov = beam_mean(bp.load_files('tirf'))
#
#    tirf_factor = frame(tirf_fov).mean() / frame(epi_fov).mean()
#    frame_factor = frame(tirf_fov).mean() / tirf_fov.mean()
#    std = 100 * frame(tirf_fov).std() / frame(tirf_fov).mean()

#   plt.imshow(tirf_mean, interpolation='none')
#   plt.colorbar()
