# -*- coding: utf-8 -*-
"""
Created on Mon Feb 17 18:23:40 2014

@author: fbaraba
"""

import numpy as np

from scipy.special import erf
from scipy.optimize import minimize
from scipy.ndimage import label
from scipy.ndimage.filters import convolve, minimum_filter, maximum_filter
from scipy.ndimage.morphology import generate_binary_structure, binary_erosion
from scipy.ndimage.measurements import center_of_mass

import pyqtgraph.ptime as ptime

import tormenta.analysis.stack as stack
import tormenta.analysis.tools as tools


# data-type definitions
parameters_2d = [('amplitude', float), ('x0', float), ('y0', float),
                 ('background', float)]
parameters = [('frame', int), ('maxima', np.int, (2,)), ('photons', float),
              ('sharpness', float), ('roundness', float),
              ('brightness', float)]
dt_2d = np.dtype(parameters + parameters_2d)


def logll(params, *args):

    A, x0, y0, bkg = params
    pico, F = args

    x, y = np.arange(pico.shape[0]), np.arange(pico.shape[1])

    erfi = erf((x + 1 - x0) / F) - erf((x - x0) / F)
    erfj = erf((y + 1 - y0) / F) - erf((y - y0) / F)

    lambda_p = A * F**2 * np.pi * erfi[:, np.newaxis] * erfj / 4 + bkg

    return - np.sum(pico * np.log(lambda_p) - lambda_p)


def ll_jac(params, *args):

    A, x0, y0, bkg = params
    pico, F = args

    x, y = np.arange(pico.shape[0]), np.arange(pico.shape[1])

    erfi = erf((x + 1 - x0) / F) - erf((x - x0) / F)
    erfj = erf((y + 1 - y0) / F) - erf((y - y0) / F)
    expi = np.exp(-(x - x0 + 1)**2/F**2) - np.exp(-(x - x0)**2/F**2)
    expj = np.exp(-(y - y0 + 1)**2/F**2) - np.exp(-(y - y0)**2/F**2)

    jac = np.zeros(4)

    # Some derivatives made with sympy

    # expr.diff(A)
    jac[0] = np.sum((np.pi/4)*F**2*pico*erfi[:, np.newaxis] * erfj/((np.pi/4)*A*F**2*erfi[:, np.newaxis] * erfj + bkg) - (np.pi/4)*F**2*erfi[:, np.newaxis] * erfj)

    jac[1] = np.sum(- 0.5 * A * F * np.sqrt(np.pi) * expi[:, np.newaxis] * erfj)

    jac[2] = np.sum(- 0.5 * A * F * np.sqrt(np.pi) * erfi[:, np.newaxis] * expj)

    # expr.diff(y0)
    jac[3] = np.sum(pico/((np.pi/4)*A*F**2*erfi[:, np.newaxis] * erfj + bkg) - 1)

    return jac


def ll_hess(params, *args):

    A, x0, y0, bkg = params
    pico, F = args

    x, y = np.arange(pico.shape[0]), np.arange(pico.shape[1])

    erfi = erf((x + 1 - x0) / F) - erf((x - x0) / F)
    erfj = erf((y + 1 - y0) / F) - erf((y - y0) / F)
    expi = np.exp(-(x - x0 + 1)**2/F**2) - np.exp(-(x - x0)**2/F**2)
    expj = np.exp(-(y - y0 + 1)**2/F**2) - np.exp(-(y - y0)**2/F**2)

    hess = np.zeros((4, 4))

    # All derivatives made with sympy

    # expr.diff(A, A)
    hess[0, 0] = - np.sum(0.616850275068085 * F**4 * pico * erfi**2 * erfj**2 /
                          ((np.pi/4) * A * F**2 * (erfi * erfj + bkg)**2))

    # expr.diff(A, x0)
    hess[0, 1] = (np.sum(F*(np.exp(-(x - x0 + 1)**2/F**2) - np.exp(-(x - x0)**2/F**2))*(erf((y - y0)/F) - erf((y - y0 + 1)/F))*(-1.23370055013617*A*F**2*pico*(erf((x - x0)/F) - erf((x - x0 + 1)/F))*(erf((y - y0)/F) - erf((y - y0 + 1)/F))/((np.pi/4)*A*F**2*(erf((x - x0)/F) - erf((x - x0 + 1)/F))*(erf((y - y0)/F) - erf((y - y0 + 1)/F)) + bkg)**2 + 1.5707963267949*pico/((np.pi/4)*A*F**2*(erf((x - x0)/F) - erf((x - x0 + 1)/F))*(erf((y - y0)/F) - erf((y - y0 + 1)/F)) + bkg) - 1.5707963267949)/np.sqrt(np.pi)))
    hess[1, 0] = hess[0, 1]

    # expr.diff(A, y0)
    hess[0, 2] = np.sum(F*(expj)*(-erfi)*(-1.23370055013617*A*F**2*pico*(-erfi)*(-erfj)/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2 + (np.pi/2)*pico/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg) - (np.pi/2))/np.sqrt(np.pi))
    hess[2, 0] = hess[0, 2]

    # expr.diff(A, bkg)
    hess[0, 3] = np.sum(-(np.pi/4)*F**2*pico*(-erfi)*(-erfj)/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2)
    hess[3, 0] = hess[0, 3]

    # expr.diff(x0, x0)
    hess[1, 1] = np.sum(A*(-erfj)*(-2.46740110027234*A*F**2*pico*(expi)**2*(-erfj)/(np.pi*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2) - np.pi*pico*((x - x0)*np.exp(-(x - x0)**2/F**2) - (x - x0 + 1)*np.exp(-(x - x0 + 1)**2/F**2))/(np.sqrt(np.pi)*F*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)) + (np.pi*(x - x0)*np.exp(-(x - x0)**2/F**2) - np.pi*(x - x0 + 1)*np.exp(-(x - x0 + 1)**2/F**2))/(np.sqrt(np.pi)*F)))

    # expr.diff(x0, y0)
    hess[1, 2] = np.sum(A*(expi)*(expj)*(-2.46740110027234*A*F**2*pico*(-erfi)*(-erfj)/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2 + np.pi*pico/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg) - np.pi)/np.pi)
    hess[2, 1] = hess[1, 2]

    # expr.diff(x0, bkg)
    hess[1, 3] = np.sum(-(np.pi/2)*A*F*pico*(expi)*(-erfj)/(np.sqrt(np.pi)*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2))
    hess[3, 1] = hess[1, 3]

    # expr.diff(y0, y0)
    hess[2, 2] = np.sum(A*(-erfi)*(-2.46740110027234*A*F**2*pico*(expj)**2*(-erfi)/(np.pi*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2) - np.pi*pico*((y - y0)*np.exp(-(y - y0)**2/F**2) - (y - y0 + 1)*np.exp(-(y - y0 + 1)**2/F**2))/(np.sqrt(np.pi)*F*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)) + (np.pi*(y - y0)*np.exp(-(y - y0)**2/F**2) - np.pi*(y - y0 + 1)*np.exp(-(y - y0 + 1)**2/F**2))/(np.sqrt(np.pi)*F)))

    # expr.diff(y0, bkg)
    hess[2, 3] = np.sum(-(np.pi/2)*A*F*pico*(expj)*(-erfi)/(np.sqrt(np.pi)*((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2))
    hess[3, 2] = hess[2, 3]

    # expr.diff(bkg, bkg)
    hess[3, 3] = np.sum(-pico/((np.pi/4)*A*F**2*(-erfi)*(-erfj) + bkg)**2)

    return hess


def fit_area(area, fwhm, bkg):

    # First guess of parameters
    F = fwhm / (2 * np.sqrt(np.log(2)))
    A = (area[np.floor(area.shape[0]/2),
              np.floor(area.shape[1]/2)] - bkg) / 0.65
    x0, y0 = center_of_mass(area)

#    return minimize(logll, x0=[A, x0, y0, bkg], args=(peak, F), jac=False,
#                    method='Newton-CG')
    return minimize(logll, x0=[A, x0, y0, bkg], args=(area, F),
                    method='Powell')

# TODO: get error of each parameter from the fit (see Powell?)


class Maxima():
    """ Class defined as the local maxima in an image frame. """

    def __init__(self, image, fwhm, kernel=None):
        self.image = image
        self.fwhm = fwhm
        self.size = np.ceil(self.fwhm)
        if kernel is None:
            self.kernel = tools.kernel(self.fwhm)

    def find(self, alpha=3):
        """Local maxima finding routine.
        Alpha is the amount of standard deviations used as a threshold of the
        local maxima search. Size is the semiwidth of the fitting window.
        Adapted from http://stackoverflow.com/questions/16842823/
                            peak-detection-in-a-noisy-2d-array
        """
        self.alpha = alpha

        # Noise removal by convolving with a null sum gaussian. Its FWHM
        # has to match the one of the objects we want to detect.
        imageConv = convolve(self.image.astype(float), self.kernel)

        # Image mask. We leave the borders out
        self.imageMask = np.ones(self.image.shape, dtype=bool)
        self.imageMask[self.size:self.image.shape[0] - self.size,
                       self.size:self.image.shape[1] - self.size] = False
        maskedArray = np.ma.masked_array(imageConv, self.imageMask)

        std = np.std(imageConv)
        mean = np.mean(imageConv)
        self.threshold = self.alpha*std + mean

        # Estimate for the maximum number of maxima in a frame
        nMax = np.ceil(self.image.size / (2*self.size + 1)**2)
        maxima = np.zeros((nMax, 2), dtype=int)
        nPeak = 0

        while 1:
            k = np.argmax(np.ma.masked_array(imageConv, self.imageMask))

            # index juggling
            j, i = np.unravel_index(k, self.image.shape)
            if(imageConv[j, i] >= self.threshold):

                # Saving the peak
                maxima[nPeak] = tuple([j, i])

                # this is the part that masks already-found maxima
                x = np.arange(i - size, i + size + 1)
                y = np.arange(j - size, j + size + 1)
                xv, yv = np.meshgrid(x, y)
                # the clip handles cases where the peak is near the image edge
                self.imageMask[yv.clip(0, self.image.shape[0] - 1),
                               xv.clip(0, self.image.shape[1] - 1)] = True

                nPeak += 1

            else:
                break

        maxima = maxima[:nPeak]

        # Drop overlapping spots
        self.positions = tools.dropOverlapping(maxima, 2 * size)
        self.overlaps = len(maxima) - len(self.positions)

    def find2(self, alpha=3):
        """
        Takes an image and detect the peaks usingthe local maximum filter.
        Returns a boolean mask of the peaks (i.e. 1 when
        the pixel's value is the neighborhood maximum, 0 otherwise). Taken from
        http://stackoverflow.com/questions/9111711/
        get-coordinates-of-local-maxima-in-2d-array-above-certain-value
        """
        self.alpha = alpha

        # Noise removal by convolving with a null sum gaussian. Its FWHM
        # has to match the one of the objects we want to detect.
        image_conv = convolve(self.image.astype(float), self.kernel)

        image_max = maximum_filter(image_conv, self.kernel.shape[0])
        maxima = (image_conv == data_max)
#        image_min = minimum_filter(image_conv, self.kernel.shape[0])
        mean = np.mean(image_conv)
#        diff = ((image_max - image_min) > self.threshold)
        self.threshold = self.alpha*np.std(image_conv) + np.mean(image_conv)
        diff = (image_max > self.threshold)

        maxima[diff == 0] = 0

        labeled, num_objects = label(maxima)
        xy = np.array(center_of_mass(self.image, labeled, range(1, num_objects+1)))

        return xy

#        plt.imshow(mm.image)
#        plt.autoscale(False)
#        plt.plot(xy[:, 1], xy[:, 0], 'ro')
#        plt.plot(mm.positions[:, 1], mm.positions[:, 0], 'ro')



#        # define an 8-connected neighborhood
#        neighborhood = np.ones((5, 5), dtype=np.dtype(bool))
#
#        # apply the local maximum filter; all pixel of maximal value
#        # in their neighborhood are set to 1
#        local_max = maximum_filter(self.image, footprint=neighborhood) == self.image
#        # local_max is a mask that contains the peaks we are
#        # looking for, but also the background.
#        # In order to isolate the peaks we must remove the background from the
#        # mask.
#
#        # we create the mask of the background
#        background = (self.image == 0)
#
#        # a little technicality: we must erode the background in order to
#        # successfully subtract it form local_max, otherwise a line will
#        # appear along the background border (artifact of the local maximum
#        # filter)
#        eroded_background = binary_erosion(background, structure=neighborhood,
#                                           border_value=1)
#
#        # we obtain the final mask, containing only peaks,
#        # by removing the background from the local_max mask
#        detected_peaks = local_max - eroded_background
#
#        return detected_peaks

    def getParameters(self):
        """Calculate the roundness, brightness, sharpness"""

        # Background estimation. Taking the mean counts of the molecule-free
        # area is good enough and ~10x faster than getting the mode
        # 215 µs vs 1.89 ms
        self.bkg = np.mean(np.ma.masked_array(self.image, imageMask))

        self.xkernel = tools.xkernel(self.fwhm)

        # Peak parameters
        roundness = np.zeros(len(self.positions))
        brightness = np.zeros(len(self.positions))

        sharpness = np.zeros(len(self.positions))
        mask = np.zeros((2*size + 1, 2*size + 1), dtype=bool)
        mask[size, size] = True

        for i in np.arange(len(self.positions)):
            # tuples make indexing easier (see below)
            p = tuple(self.positions[i])

            # Sharpness
            masked = np.ma.masked_array(self.area(i), mask)
            sharpness[i] = self.image[p] / (imageConv[p] * masked.mean())

            # Roundness
            hx = np.dot(self.area(i)[2, :], self.xkernel)
            hy = np.dot(self.area(i)[:, 2], self.xkernel)
            roundness[i] = 2 * (hy - hx) / (hy + hx)

            # Brightness
            brightness[i] = 2.5 * np.log(imageConv[p] / self.alpha*std)

        self.sharpness = sharpness
        self.roundness = roundness
        self.brightness = brightness

    def area(self, n):
        """Returns the area around the local maximum number n."""
        coord = self.positions[n]
        return self.image[coord[0] - self.size:coord[0] + self.size + 1,
                          coord[1] - self.size:coord[1] + self.size + 1]

    def fit(self, fit_model='2d'):

        if fit_model is '2d':
            fit_par = [x[0] for x in parameters_2d]
            self.results = np.zeros(len(self.positions), dtype=dt_2d)

        for i in np.arange(len(self.positions)):

            # Fit and store fitting results
            area = self.area(i)
            res = fit_area(area, self.fwhm, self.bkg)
            res.x[1:3] = (res.x[1:3] - self.size - 0.5 + self.positions[i])
            for p in np.arange(len(fit_par)):
                self.results[fit_par[p]][i] = res.x[p]

            # photons from molecule calculation
            self.results['photons'][i] = (np.sum(area)
                                          - area.size * res.x[-1])

        self.results['maxima'] = self.positions
        self.results['sharpness'] = self.sharpness
        self.results['roundness'] = self.roundness
        self.results['brightness'] = self.brightness


if __name__ == "__main__":

    stack = stack.Stack()
    maxima = Maxima(stack.image[10], stack.fwhm)
