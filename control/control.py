# -*- coding: utf-8 -*-
"""
Created on Mon Jun 16 18:19:24 2014

@author: Federico Barabas
"""

import numpy as np
import os
import time

from PyQt4 import QtGui, QtCore

import pyqtgraph as pg
import pyqtgraph.ptime as ptime
from pyqtgraph.parametertree import Parameter, ParameterTree

import h5py as hdf

# Lantz drivers
from lantz.drivers.andor.ccd import CCD
# from lantz.drivers.cobolt import Cobolt0601
from lantz.drivers.rgblasersystems import MiniLasEvo
from lantz.drivers.mpb import VFL
from lantz import Q_

from lasercontrol import LaserWidget, Laser
from simulators import SimCamera

degC = Q_(1, 'degC')
us = Q_(1, 'us')
MHz = Q_(1, 'MHz')
s = Q_(1, 's')
mW = Q_(1, 'mW')

lastTime = ptime.time()
fps = None

app = QtGui.QApplication([])

# TODO: Implement cropped sensor mode in case we want higher framerates

class Camera(object):

    def __new__(cls, driver, *args):

        try:
            return driver(*args)

        except:
            return SimCamera()


class RecordingWidget(QtGui.QFrame):

    def __init__(self, *args, **kwargs):
        super(QtGui.QFrame, self).__init__(*args, **kwargs)

        recTitle = QtGui.QLabel('<h2><strong>Recording settings</strong></h2>')
        recTitle.setTextFormat(QtCore.Qt.RichText)
        self.setFrameStyle(QtGui.QFrame.Panel | QtGui.QFrame.Raised)
        recGrid = QtGui.QGridLayout()
        self.setLayout(recGrid)
        numExpositions = QtGui.QLabel('Number of expositions')
        self.numExpositionsEdit = QtGui.QLineEdit('100')
        folderLabel = QtGui.QLabel('Folder')
        self.folderEdit = QtGui.QLineEdit(os.getcwd())
        filenameLabel = QtGui.QLabel('Filename')
        self.filenameEdit = QtGui.QLineEdit('filename.hdf5')

        self.snapButton = QtGui.QPushButton('Snap')
        self.snapButton.setEnabled(False)
        self.snapButton.setSizePolicy(QtGui.QSizePolicy.Preferred,
                                      QtGui.QSizePolicy.Expanding)

        self.recButton = QtGui.QPushButton('REC')
        self.recButton.setCheckable(True)
        self.recButton.setEnabled(False)
        self.recButton.setSizePolicy(QtGui.QSizePolicy.Preferred,
                                     QtGui.QSizePolicy.Expanding)

        self.convertButton = QtGui.QPushButton('Convert to .tiff')

        recGrid.addWidget(recTitle, 0, 0, 1, 3)
        recGrid.addWidget(numExpositions, 1, 0)
        recGrid.addWidget(self.numExpositionsEdit, 1, 1)
        recGrid.addWidget(folderLabel, 2, 0, 1, 2)
        recGrid.addWidget(self.folderEdit, 3, 0, 1, 2)
        recGrid.addWidget(filenameLabel, 4, 0, 1, 2)
        recGrid.addWidget(self.filenameEdit, 5, 0, 1, 2)
        recGrid.addWidget(self.snapButton, 1, 2, 2, 1)
        recGrid.addWidget(self.recButton, 3, 2, 2, 1)
        recGrid.addWidget(self.convertButton, 5, 2)

    def nExpositions(self):
        return int(self.numExpositionsEdit.text())

    def folder(self):
        return self.folderEdit.text()

    def filename(self):
        return self.filenameEdit.text()


def setCameraDefaults(camera):
    """ Initial camera's configuration
    """
    camera.readout_mode = 'Image'
    camera.trigger_mode = 'Internal'
    camera.preamp = 0
    camera.EM_advanced_enabled = False
    camera.EM_gain_mode = 'RealGain'
    camera.amp_typ = 0
    camera.vert_shift_speed = 0
    camera.set_n_accum(1)                 # No accumulation of exposures
    camera.set_accum_time(0 * s)          # Minimum accumulation and kinetic
    camera.set_kinetic_cycle_time(0 * s)  # times
    camera.horiz_shift_speed = 3


class TemperatureStabilizer(QtCore.QObject):

    def __init__(self, parameter, *args, **kwargs):

        global andor

        super(QtCore.QObject, self).__init__(*args, **kwargs)
        self.parameter = parameter

    def start(self):
        SetPointPar = self.parameter.param('Set point')
        andor.temperature_setpoint = SetPointPar.value() * degC
        andor.cooler_on = True
        stable = 'Temperature has stabilized at set point.'
        CurrTempPar = self.parameter.param('Current temperature')
        while andor.temperature_status != stable:
            CurrTempPar.setValue(np.round(andor.temperature.magnitude, 1))
            self.parameter.param('Status').setValue(andor.temperature_status)
            time.sleep(10)


class TormentaGUI(QtGui.QMainWindow):

    def __init__(self, *args, **kwargs):

        global andor

        super(QtGui.QMainWindow, self).__init__(*args, **kwargs)
        self.setWindowTitle('Tormenta')
        self.cwidget = QtGui.QWidget()
        self.setCentralWidget(self.cwidget)

        # Lists needed for the parameter tree
        self.PreAmps = np.around([andor.true_preamp(n)
                                  for n in np.arange(andor.n_preamps)],
                                 decimals=1)
        self.HRRates = [andor.true_horiz_shift_speed(n)
                        for n in np.arange(andor.n_horiz_shift_speeds())]

        # Parameter tree for the camera configuration
        params = [{'name': 'Camera', 'type': 'str',
                   'value': andor.idn.split(',')[0]},
                  {'name': 'Image frame', 'type': 'group', 'children': [
                   {'name': 'x_start', 'type': 'int', 'suffix': 'px',
                    'value': 1},
                   {'name': 'y_start', 'type': 'int', 'suffix': 'px',
                    'value': 1},
                   {'name': 'x_size', 'type': 'int', 'suffix': 'px',
                    'value': andor.detector_shape[0]},
                   {'name': 'y_size', 'type': 'int', 'suffix': 'px',
                    'value': andor.detector_shape[1]},
                   {'name': 'Update', 'type': 'action'},
                   ]},
                  {'name': 'Timings', 'type': 'group', 'children': [
                   {'name': 'Frame Transfer Mode', 'type': 'bool',
                    'value': False},
                   {'name': 'Horizontal readout rate', 'type': 'list',
                    'values': self.HRRates[::-1]},
                   {'name': 'Set exposure time', 'type': 'float',
                    'value': 0.1, 'limits': (0, andor.max_exposure.magnitude),
                    'siPrefix': True, 'suffix': 's'},
                   {'name': 'Real exposure time', 'type': 'float',
                    'value': 0, 'readonly': True, 'siPrefix': True,
                    'suffix': 's'},
                   {'name': 'Real accumulation time', 'type': 'float',
                    'value': 0, 'readonly': True, 'siPrefix': True,
                    'suffix': 's'},
                   {'name': 'Effective frame rate', 'type': 'float',
                    'value': 0, 'readonly': True, 'siPrefix': True,
                    'suffix': 'Hz'},
                   ]},
                  {'name': 'Gain', 'type': 'group', 'children': [
                   {'name': 'Pre-amp gain', 'type': 'list',
                    'values': list(self.PreAmps)},
                   {'name': 'EM gain', 'type': 'int', 'value': 1,
                    'limits': (0, andor.EM_gain_range[1])}
                   ]},
                  {'name': 'Temperature', 'type': 'group', 'children': [
                   {'name': 'Set point', 'type': 'int', 'value': -40,
                    'suffix': 'º', 'limits': (-80, 0)},
                   {'name': 'Current temperature', 'type': 'int',
                    'value': andor.temperature.magnitude, 'suffix': 'ºC',
                    'readonly': True},
                   {'name': 'Status', 'type': 'str', 'readonly': True,
                    'value': andor.temperature_status},
                   {'name': 'Stabilize', 'type': 'action'},
                   ]}]

        self.p = Parameter.create(name='params', type='group', children=params)
        tree = ParameterTree()
        tree.setParameters(self.p, showTop=False)

        # Frame signals
        frameUpdateButton = self.p.param('Image frame').param('Update')
        changeFrame = lambda: self.changeParameter(self.updateFrame)
        frameUpdateButton.sigStateChanged.connect(changeFrame)

        # Exposition signals
        self.TimingsPar = self.p.param('Timings')
        self.ExpPar = self.TimingsPar.param('Set exposure time')
        self.FTMPar = self.TimingsPar.param('Frame Transfer Mode')
        self.HRRatePar = self.TimingsPar.param('Horizontal readout rate')
        changeExposure = lambda: self.changeParameter(self.setExposure)
        self.ExpPar.sigValueChanged.connect(changeExposure)
        self.FTMPar.sigValueChanged.connect(changeExposure)
        self.HRRatePar.sigValueChanged.connect(changeExposure)

        # Gain signals
        self.PreGainPar = self.p.param('Gain').param('Pre-amp gain')
        updateGain = lambda: self.changeParameter(self.setGain)
        self.PreGainPar.sigValueChanged.connect(updateGain)
        self.GainPar = self.p.param('Gain').param('EM gain')
        self.GainPar.sigValueChanged.connect(updateGain)

        # Recording signals
        self.dataname = 'data'      # In case I need a QLineEdit for this
        self.recWidget = RecordingWidget()
        self.recWidget.recButton.clicked.connect(self.record)
        self.recWidget.snapButton.clicked.connect(self.snap)
        self.recWidget.convertButton.clicked.connect(self.convertToRaw)

        # Image Widget
        # TODO: redefine axis ticks
        imagewidget = pg.GraphicsLayoutWidget()
        self.p1 = imagewidget.addPlot()
        self.p1.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.img = pg.ImageItem()
        self.img.translate(-0.5, -0.5)
        self.p1.addItem(self.img)
        self.p1.getViewBox().setAspectLocked(True)
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.hist.autoHistogramRange = False
        self.hist.setLevels(90, 110)
        imagewidget.addItem(self.hist)

        self.fpsbox = QtGui.QLabel()

        # Initial camera configuration taken from the parameter tree
        setCameraDefaults(andor)
        andor.set_exposure_time(self.ExpPar.value() * s)
        self.adjustFrame()
        self.updateTimings()

        # Liveview functionality
        liveviewButton = QtGui.QPushButton('Liveview')
        liveviewButton.setCheckable(True)
        liveviewButton.pressed.connect(self.liveview)
        self.viewtimer = QtCore.QTimer()
        self.viewtimer.timeout.connect(self.updateView)

        # Temperature stabilization functionality
        self.TempPar = self.p.param('Temperature')
        stabButton = self.TempPar.param('Stabilize')
        self.stabilizer = TemperatureStabilizer(self.TempPar)
        self.stabilizerThread = QtCore.QThread()
        self.stabilizer.moveToThread(self.stabilizerThread)
        stabButton.sigStateChanged.connect(self.stabilizerThread.start)
        self.stabilizerThread.started.connect(self.stabilizer.start)

        # Laser control widget
        self.laserWidgets = LaserWidget((redlaser, bluelaser))

        # Widgets' layout
        layout = QtGui.QGridLayout()
        self.cwidget.setLayout(layout)
        layout.setColumnMinimumWidth(1, 400)
        layout.setColumnMinimumWidth(2, 800)
        layout.setColumnMinimumWidth(3, 200)
        layout.setRowMinimumHeight(1, 150)
        layout.setRowMinimumHeight(2, 250)
        layout.addWidget(tree, 1, 1, 2, 1)
        layout.addWidget(liveviewButton, 3, 1)
        layout.addWidget(self.recWidget, 4, 1)
        layout.addWidget(imagewidget, 1, 2, 4, 1)
        layout.addWidget(self.fpsbox, 0, 2)
        layout.addWidget(self.laserWidgets, 1, 3)

    def changeParameter(self, function):
        """ This method is used to change those camera properties that need
        the camera to be idle to be able to be adjusted.
        """
        status = andor.status
        if status != ('Camera is idle, waiting for instructions.'):
            self.viewtimer.stop()
            andor.abort_acquisition()

        function()

        if status != ('Camera is idle, waiting for instructions.'):
            andor.start_acquisition()
            time.sleep(np.min((5 * self.t_exp_real.magnitude, 1)))
            self.viewtimer.start(0)

    def setGain(self):
        """ Method to change the pre-amp gain and main gain of the EMCCD
        """
        PreAmpGain = self.PreGainPar.value()
        n = np.where(self.PreAmps == PreAmpGain)[0][0]
        andor.preamp = n
        andor.EM_gain = self.GainPar.value()

    def setExposure(self):
        """ Method to change the exposure time setting
        """
        andor.set_exposure_time(self.ExpPar.value() * s)
        andor.frame_transfer_mode = self.FTMPar.value()
        HRRate = self.HRRatePar.value()
        HRRatesMagnitude = np.array([item.magnitude for item in self.HRRates])
        n = np.where(HRRatesMagnitude == HRRate.magnitude)[0][0]
        andor.horiz_shift_speed = n
        self.updateTimings()

    def adjustFrame(self):
        """ Method to change the area of the CCD to be used and adjust the
        image widget accordingly.
        """
        self.shape = [self.p.param('Image frame').param('x_size').value(),
                      self.p.param('Image frame').param('y_size').value()]
        self.p_0 = [self.p.param('Image frame').param('x_start').value(),
                    self.p.param('Image frame').param('y_start').value()]
        andor.set_image(shape=self.shape, p_0=self.p_0)
        self.p1.setRange(xRange=(-0.5, self.shape[0] - 0.5),
                         yRange=(-0.5, self.shape[1] - 0.5), padding=0)
        self.p1.getViewBox().setLimits(xMin=-0.5, xMax=self.shape[0] - 0.5,
                                       yMin=-0.5, yMax=self.shape[1] - 0.5,
                                       minXRange=4, minYRange=4)

    def updateFrame(self):
        """ Method to change the image frame size and position in the sensor
        """
        self.adjustFrame()
        self.updateTimings()

    def updateTimings(self):
        """ Update the real exposition and accumulation times in the parameter
        tree.
        """
        timings = andor.acquisition_timings
        self.t_exp_real, self.t_acc_real, self.t_kin_real = timings
        RealExpPar = self.p.param('Timings').param('Real exposure time')
        RealAccPar = self.p.param('Timings').param('Real accumulation time')
        EffFRPar = self.p.param('Timings').param('Effective frame rate')
        RealExpPar.setValue(self.t_exp_real)
        RealAccPar.setValue(self.t_acc_real)
        EffFRPar.setValue(1 / self.t_acc_real)

    def liveview(self):
        """ Image live view when not recording
        """
        if andor.status != 'Camera is idle, waiting for instructions.':
            andor.abort_acquisition()

        andor.acquisition_mode = 'Run till abort'
        andor.shutter(0, 1, 0, 0, 0)

        andor.start_acquisition()
        time.sleep(np.min((5 * self.t_exp_real, 1)))
        self.recWidget.snapButton.setEnabled(True)
        self.recWidget.recButton.setEnabled(True)
        self.viewtimer.start(0)

    def updateView(self):
        """ Image update while in Liveview mode
        """
        global lastTime, fps
        try:
            image = andor.most_recent_image16(self.shape)
            self.img.setImage(image, autoLevels=False)
            now = ptime.time()
            dt = now - lastTime
            lastTime = now
            if fps is None:
                fps = 1.0/dt
            else:
                s = np.clip(dt*3., 0, 1)
                fps = fps * (1-s) + (1.0/dt) * s
            self.fpsbox.setText('%0.2f fps' % fps)
        except:
            pass

    def snap(self):

        image = andor.most_recent_image16(self.shape)

        # Data storing
        self.folder = self.recWidget.folder()
        self.filename = self.recWidget.filename()
        self.n = self.recWidget.nExpositions()
        self.store_file = hdf.File(os.path.join(self.folder, self.filename),
                                   "w")
        self.store_file.create_dataset(name=self.dataname + '_snap', data=image)
        # TODO: add attributes
        self.store_file.close()

    def record(self):

        self.j = 0

        # Data storing
        self.folder = self.recWidget.folder()
        self.filename = self.recWidget.filename()
        self.n = self.recWidget.nExpositions()
        self.store_file = hdf.File(os.path.join(self.folder, self.filename),
                                   "w")
        self.store_file.create_dataset(name=self.dataname,
                                       shape=(self.n,
                                              self.shape[0],
                                              self.shape[1]),
                                       fillvalue=0.0)
        self.stack = self.store_file['data']

        # Acquisition preparation
        if andor.status != 'Camera is idle, waiting for instructions.':
            andor.abort_acquisition()
        else:
            andor.shutter(0, 1, 0, 0, 0)

        andor.free_int_mem()
        andor.acquisition_mode = 'Kinetics'
        andor.set_n_kinetics(self.n)
        andor.start_acquisition()
        time.sleep(np.min((5 * self.t_exp_real.magnitude, 1)))

        # Stop the QTimer that updates the image with incoming data from the
        # 'Run till abort' acquisition mode.
        self.viewtimer.stop()
        QtCore.QTimer.singleShot(1, self.updateWhileRec)

    def updateWhileRec(self):
        global lastTime, fps

        if andor.n_images_acquired > self.j:
            i, self.j = andor.new_images_index
            self.stack[i - 1:self.j] = andor.images16(i, self.j, self.shape,
                                                      1, self.n)
            self.img.setImage(self.stack[self.j - 1], autoLevels=False)

            now = ptime.time()
            dt = now - lastTime
            lastTime = now
            if fps is None:
                fps = 1.0/dt
            else:
                s = np.clip(dt*3., 0, 1)
                fps = fps * (1-s) + (1.0/dt) * s
            self.fpsbox.setText('%0.2f fps' % fps)

        if self.j < self.n:     # It hasn't finished
            QtCore.QTimer.singleShot(0, self.UpdateWhileRec)

        else:                   # The recording is over
            self.j = 0

            # Saving parameters as data attributes in the HDF5 file
            dset = self.store_file[self.dataname]
            dset.attrs['Date'] = time.strftime("%Y-%m-%d")
            dset.attrs['Time'] = time.strftime("%H:%M:%S")
            for ParamName in self.p.getValues():
                Param = self.p.param(str(ParamName))
                if not(Param.hasChildren()):
                    dset.attrs[str(ParamName)] = Param.value()
                for subParamName in Param.getValues():
                    subParam = Param.param(str(subParamName))
                    if subParam.type() != 'action':
                        dset.attrs[str(subParamName)] = subParam.value()

            self.store_file.close()
            self.recWidget.recButton.setChecked(False)
            self.liveview()

    def convertToRaw(self):

        # TODO: implement this
        self.store_file = hdf.File(os.path.join(self.folder, self.filename),
                                   "r")

    def closeEvent(self, *args, **kwargs):

        self.laserWidgets.closeEvent()

        # Stop running threads
        self.viewtimer.stop()
        self.stabilizerThread.terminate()

        # Turn off camera, close shutter
        if andor.status != 'Camera is idle, waiting for instructions.':
            andor.abort_acquisition()
        andor.shutter(0, 2, 0, 0, 0)

        super(QtGui.QMainWindow, self).closeEvent(*args, **kwargs)


if __name__ == '__main__':

    from lantz import Q_
    s = Q_(1, 's')

#    with Camera(CCD()) as andor, Laser(VFL, 'COM5') as redlaser, \
#            Laser(MiniLasEvo, 'COM7') as bluelaser:

    with SimCamera() as andor, Laser(VFL, 'COM5') as redlaser, \
            Laser(MiniLasEvo, 'COM7') as bluelaser:

        print(andor.idn)
        print(redlaser.idn)
        print(bluelaser.idn)

        win = TormentaGUI()
        win.show()

        app.exec_()
