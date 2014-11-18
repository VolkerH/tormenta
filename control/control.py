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
# http://www.lfd.uci.edu/~gohlke/pythonlibs/#vlfd
# http://www.lfd.uci.edu/~gohlke/
import tifffile as tiff

# Lantz drivers
from lantz.drivers.andor.ccd import CCD
from lantz.drivers.cobolt import Cobolt0601
from lantz.drivers.mpb import VFL
from lantz.drivers.laserquantum import Ventus
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

        self.currentFrame = QtGui.QLabel('0 /')
        self.numExpositionsEdit = QtGui.QLineEdit('100')
        self.folderEdit = QtGui.QLineEdit(os.getcwd())
        self.filenameEdit = QtGui.QLineEdit('filename')
        self.formatBox = QtGui.QComboBox()
        self.formatBox.addItems(['tiff', 'hdf5'])

        self.snapButton = QtGui.QPushButton('Snap')
        self.snapButton.setEnabled(False)
        self.snapButton.setSizePolicy(QtGui.QSizePolicy.Preferred,
                                      QtGui.QSizePolicy.Expanding)
        self.recButton = QtGui.QPushButton('REC')
        self.recButton.setCheckable(True)
        self.recButton.setEnabled(False)
        self.recButton.setSizePolicy(QtGui.QSizePolicy.Preferred,
                                     QtGui.QSizePolicy.Expanding)

        recGrid = QtGui.QGridLayout()
        self.setLayout(recGrid)
        recGrid.addWidget(recTitle, 0, 0, 1, 3)
        recGrid.addWidget(QtGui.QLabel('Number of expositions'), 5, 0)
        recGrid.addWidget(self.currentFrame, 5, 1)
        recGrid.addWidget(self.numExpositionsEdit, 5, 2)
        recGrid.addWidget(QtGui.QLabel('Folder'), 1, 0, 1, 2)
        recGrid.addWidget(self.folderEdit, 2, 0, 1, 3)
        recGrid.addWidget(QtGui.QLabel('Filename'), 3, 0, 1, 2)
        recGrid.addWidget(self.filenameEdit, 4, 0, 1, 2)
        recGrid.addWidget(self.formatBox, 4, 2)
        recGrid.addWidget(self.snapButton, 1, 3, 2, 1)
        recGrid.addWidget(self.recButton, 3, 3, 3, 1)

        recGrid.setColumnMinimumWidth(0, 200)

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
    camera.vert_shift_speed = 4
    camera.set_n_accum(1)                 # No accumulation of exposures
    camera.set_accum_time(0 * s)          # Minimum accumulation and kinetic
    camera.set_kinetic_cycle_time(0 * s)  # times
    camera.horiz_shift_speed = 3
    camera.set_vert_clock(0)


class TemperatureStabilizer(QtCore.QObject):

    def __init__(self, parameter, *args, **kwargs):

        global andor

        super(QtCore.QObject, self).__init__(*args, **kwargs)
        self.parameter = parameter
        self.setPointPar = self.parameter.param('Set point')
        self.setPointPar.sigValueChanged.connect(self.updateTemp)

    def updateTemp(self):
        andor.temperature_setpoint = Q_(self.setPointPar.value(), 'degC')

    def start(self):
        self.updateTemp()
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
        self.vertSpeeds = [np.round(andor.true_vert_shift_speed(n), 1)
                           for n in np.arange(andor.n_vert_shift_speeds)]
        self.vertAmps = ['+' + str(andor.true_vert_amp(n))
                         for n in np.arange(andor.n_vert_clock_amps)]
        self.vertAmps[0] = 'Normal'

        # Parameter tree for the camera configuration
        params = [{'name': 'Camera', 'type': 'str',
                   'value': andor.idn.split(',')[0]},
                  {'name': 'Image frame', 'type': 'group', 'children': [
                      {'name': 'Size', 'type': 'list',
                       'values': ['Full chip', '256x256', '128x128', '64x64',
                                  'Custom']}]},
                  {'name': 'Timings', 'type': 'group', 'children': [
                      {'name': 'Frame Transfer Mode', 'type': 'bool',
                       'value': False},
                      {'name': 'Horizontal readout rate', 'type': 'list',
                       'values': self.HRRates[::-1]},
                      {'name': 'Vertical pixel shift', 'type': 'group',
                       'children': [
                           {'name': 'Speed', 'type': 'list',
                            'values': self.vertSpeeds[::-1]},
                           {'name': 'Clock voltage amplitude',
                            'type': 'list', 'values': self.vertAmps}]},
                      {'name': 'Set exposure time', 'type': 'float',
                       'value': 0.1, 'limits': (0,
                                                andor.max_exposure.magnitude),
                       'siPrefix': True, 'suffix': 's'},
                      {'name': 'Real exposure time', 'type': 'float',
                       'value': 0, 'readonly': True, 'siPrefix': True,
                       'suffix': 's'},
                      {'name': 'Real accumulation time', 'type': 'float',
                       'value': 0, 'readonly': True, 'siPrefix': True,
                       'suffix': 's'},
                      {'name': 'Effective frame rate', 'type': 'float',
                       'value': 0, 'readonly': True, 'siPrefix': True,
                       'suffix': 'Hz'}]},
                  {'name': 'Gain', 'type': 'group', 'children': [
                      {'name': 'Pre-amp gain', 'type': 'list',
                       'values': list(self.PreAmps)},
                      {'name': 'EM gain', 'type': 'int', 'value': 1,
                       'limits': (0, andor.EM_gain_range[1])}]},
                  {'name': 'Temperature', 'type': 'group', 'children': [
                      {'name': 'Set point', 'type': 'int', 'value': -70,
                       'suffix': 'º', 'limits': (-80, 0)},
                      {'name': 'Current temperature', 'type': 'int',
                       'value': andor.temperature.magnitude, 'suffix': 'ºC',
                       'readonly': True},
                      {'name': 'Status', 'type': 'str', 'readonly': True,
                       'value': andor.temperature_status}]}]

        self.customParam = {'name': 'Custom', 'type': 'group', 'children': [
                            {'name': 'x_start', 'type': 'int', 'suffix': 'px',
                             'value': 1},
                            {'name': 'y_start', 'type': 'int', 'suffix': 'px',
                             'value': 1},
                            {'name': 'x_size', 'type': 'int', 'suffix': 'px',
                             'value': andor.detector_shape[0]},
                            {'name': 'y_size', 'type': 'int', 'suffix': 'px',
                             'value': andor.detector_shape[1]},
                            {'name': 'Apply', 'type': 'action'}]}

        self.p = Parameter.create(name='params', type='group', children=params)
        tree = ParameterTree()
        tree.setParameters(self.p, showTop=False)

        # Frame signals
        self.shape = andor.detector_shape
        frameParam = self.p.param('Image frame')
        frameParam.param('Size').sigValueChanged.connect(self.updateFrame)

        # Exposition signals
        changeExposure = lambda: self.changeParameter(self.setExposure)
        TimingsPar = self.p.param('Timings')
        self.ExpPar = TimingsPar.param('Set exposure time')
        self.ExpPar.sigValueChanged.connect(changeExposure)
        self.FTMPar = TimingsPar.param('Frame Transfer Mode')
        self.FTMPar.sigValueChanged.connect(changeExposure)
        self.HRRatePar = TimingsPar.param('Horizontal readout rate')
        self.HRRatePar.sigValueChanged.connect(changeExposure)
        vertShiftPar = TimingsPar.param('Vertical pixel shift')
        self.vertShiftSpeedPar = vertShiftPar.param('Speed')
        self.vertShiftSpeedPar.sigValueChanged.connect(changeExposure)
        self.vertShiftAmpPar = vertShiftPar.param('Clock voltage amplitude')
        self.vertShiftAmpPar.sigValueChanged.connect(changeExposure)

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

        # Image Widget
        # TODO: redefine axis ticks
        self.shape = andor.detector_shape
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
        imagewidget.addItem(self.hist)

        # TODO: x, y profiles
        self.fpsBox = QtGui.QLabel()
        self.gridBox = QtGui.QCheckBox('Show grid')
        self.gridBox.stateChanged.connect(self.toggleGrid)

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
        self.stabilizer = TemperatureStabilizer(self.TempPar)
        self.stabilizerThread = QtCore.QThread()
        self.stabilizer.moveToThread(self.stabilizerThread)
        self.stabilizerThread.started.connect(self.stabilizer.start)
        self.stabilizerThread.start()

        # Laser control widget
        self.laserWidgets = LaserWidget((redlaser, bluelaser, greenlaser))

        # Widgets' layout
        layout = QtGui.QGridLayout()
        self.cwidget.setLayout(layout)
        layout.setColumnMinimumWidth(0, 400)
        layout.setColumnMinimumWidth(1, 800)
        layout.setColumnMinimumWidth(2, 200)
        layout.setRowMinimumHeight(0, 150)
        layout.setRowMinimumHeight(1, 320)
        layout.addWidget(tree, 0, 0, 2, 1)
        layout.addWidget(liveviewButton, 2, 0)
        layout.addWidget(self.recWidget, 3, 0, 2, 1)
        layout.addWidget(imagewidget, 0, 1, 4, 3)
        layout.addWidget(self.fpsBox, 4, 1)
        layout.addWidget(self.gridBox, 4, 2)
        layout.addWidget(self.laserWidgets, 0, 4)

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
        n_hrr = np.where(np.array([item.magnitude for item in self.HRRates])
                         == self.HRRatePar.value().magnitude)[0][0]
        andor.horiz_shift_speed = n_hrr

        n_vss = np.where(np.array([item.magnitude for item in self.vertSpeeds])
                         == self.vertShiftSpeedPar.value().magnitude)[0][0]
        andor.vert_shift_speed = n_vss

        n_vsa = np.where(np.array(self.vertAmps) ==
                         self.vertShiftAmpPar.value())[0][0]
        andor.set_vert_clock(n_vsa)

        self.updateTimings()

    # TODO: grid for ROIs
    # TODO: create grid class

    """ Grid methods """
    def showGrid(self):
        self.yline1 = pg.InfiniteLine(pos=0.25*self.shape[0], pen='y')
        self.yline2 = pg.InfiniteLine(pos=0.50*self.shape[0], pen='y')
        self.yline3 = pg.InfiniteLine(pos=0.75*self.shape[0], pen='y')
        self.xline1 = pg.InfiniteLine(pos=0.25*self.shape[1], pen='y', angle=0)
        self.xline2 = pg.InfiniteLine(pos=0.50*self.shape[1], pen='y', angle=0)
        self.xline3 = pg.InfiniteLine(pos=0.75*self.shape[1], pen='y', angle=0)
        self.p1.getViewBox().addItem(self.xline1)
        self.p1.getViewBox().addItem(self.xline2)
        self.p1.getViewBox().addItem(self.xline3)
        self.p1.getViewBox().addItem(self.yline1)
        self.p1.getViewBox().addItem(self.yline2)
        self.p1.getViewBox().addItem(self.yline3)

    def hideGrid(self):
        self.p1.getViewBox().removeItem(self.xline1)
        self.p1.getViewBox().removeItem(self.xline2)
        self.p1.getViewBox().removeItem(self.xline3)
        self.p1.getViewBox().removeItem(self.yline1)
        self.p1.getViewBox().removeItem(self.yline2)
        self.p1.getViewBox().removeItem(self.yline3)

    def toggleGrid(self, state):
        if state == QtCore.Qt.Checked:
            self.showGrid()
        else:
            self.hideGrid()

    def adjustFrame(self, shape=None, start=(1, 1)):
        """ Method to change the area of the CCD to be used and adjust the
        image widget accordingly.
        """
        if shape is None:
            shape = self.shape

        andor.set_image(shape=shape, p_0=start)
        self.p1.setRange(xRange=(-0.5, shape[0] - 0.5),
                         yRange=(-0.5, shape[1] - 0.5), padding=0)
        self.p1.getViewBox().setLimits(xMin=-0.5, xMax=shape[0] - 0.5,
                                       yMin=-0.5, yMax=shape[1] - 0.5,
                                       minXRange=4, minYRange=4)
        if self.gridBox.isChecked():
            self.hideGrid()
            self.showGrid()

        self.updateTimings()

    def updateFrame(self):
        """ Method to change the image frame size and position in the sensor
        """
        frameParam = self.p.param('Image frame')
        if frameParam.param('Size').value() == 'Custom':

            # Add new parameters for custom frame setting
            frameParam.addChild(self.customParam)
            customParam = frameParam.param('Custom')

            # Signals
            applyParam = customParam.param('Apply')
            applyParam.sigStateChanged.connect(self.customFrame)

        elif frameParam.param('Size').value() == 'Full chip':
            self.shape = andor.detector_shape
            self.changeParameter(self.adjustFrame)

        else:
            side = int(frameParam.param('Size').value().split('x')[0])
            start = (int(0.5 * (andor.detector_shape[0] - side)),
                     int(0.5 * (andor.detector_shape[1] - side)))
            self.shape = (side, side)
            self.changeParameter(lambda: self.adjustFrame(self.shape, start))

    def customFrame(self):
        customParam = self.p.param('Image frame').param('Custom')

        self.shape = (customParam.param('x_size').value(),
                      customParam.param('y_size').value())
        start = (customParam.param('x_start').value(),
                 customParam.param('y_start').value())


        self.changeParameter(lambda: self.adjustFrame(self.shape, start))

    def updateTimings(self):
        """ Update the real exposition and accumulation times in the parameter
        tree.
        """
        timings = andor.acquisition_timings
        self.t_exp_real, self.t_acc_real, self.t_kin_real = timings
        RealExpPar = self.p.param('Timings').param('Real exposure time')
        RealAccPar = self.p.param('Timings').param('Real accumulation time')
        EffFRPar = self.p.param('Timings').param('Effective frame rate')
        RealExpPar.setValue(self.t_exp_real.magnitude)
        RealAccPar.setValue(self.t_acc_real.magnitude)
        EffFRPar.setValue(1 / self.t_acc_real.magnitude)

    def liveview(self):
        """ Image live view when not recording
        """
        if andor.status != 'Camera is idle, waiting for instructions.':
            andor.abort_acquisition()

        andor.acquisition_mode = 'Run till abort'
        andor.shutter(0, 1, 0, 0, 0)

        andor.start_acquisition()
        time.sleep(np.min((5 * self.t_exp_real.magnitude, 1)))
        self.recWidget.snapButton.setEnabled(True)
        self.recWidget.recButton.setEnabled(True)

        # Initial image
        image = andor.most_recent_image16(self.shape)
        self.img.setImage(image)
        self.hist.setLevels(np.min(image) - np.std(image),
                            np.max(image) + np.std(image))

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
            self.fpsBox.setText('%0.2f fps' % fps)
        except:
            pass

    def snap(self):

        image = andor.most_recent_image16(self.shape)

        # TODO: snap format tiff

        # Data storing
        self.folder = self.recWidget.folder()
        self.filename = self.recWidget.filename()
        self.format = self.recWidget.formatBox.currentText()

        if self.format == 'hdf5':
            self.store_file = hdf.File(os.path.join(self.folder,
                                                    self.filename) + '.hdf5')
            self.store_file.create_dataset(name=self.dataname + '_snap',
                                           data=image)
            self.store_file.close()

#        elif self.format == 'tiff':

    def record(self):

        # TODO: x, y histograms
        # TODO: disable buttons while recording

        # Frame counter
        self.j = 0

        # Data storing
        self.recPath = self.recWidget.folder()
        self.recFilename = self.recWidget.filename()
        self.n = self.recWidget.nExpositions()
        self.format = self.recWidget.formatBox.currentText()

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

        if self.format == 'hdf5':
            """ Useful format for big data as it saves new frames in chunks.
            Therefore, you don't have the whole stack in memory."""

            self.store_file = hdf.File(os.path.join(self.recPath,
                                                    self.recFilename)
                                       + '.hdf5', "w")
            self.store_file.create_dataset(name=self.dataname,
                                           shape=(self.n,
                                                  self.shape[0],
                                                  self.shape[1]),
                                           fillvalue=0, dtype=np.uint16)
            self.stack = self.store_file['data']

        elif self.format == 'tiff':
            """ This format has the problem of placing the whole stack in
            memory before saving."""

            self.stack = np.empty((self.n, self.shape[0], self.shape[1]),
                                  dtype=np.uint16)

        QtCore.QTimer.singleShot(1, self.updateWhileRec)

    def updateWhileRec(self):
        global lastTime, fps

        time.sleep(self.t_exp_real.magnitude)

        if andor.n_images_acquired > self.j:
            i, self.j = andor.new_images_index
            self.stack[i - 1:self.j] = andor.images16(i, self.j, self.shape,
                                                      1, self.n)
            self.img.setImage(self.stack[self.j - 1], autoLevels=False)
            self.recWidget.currentFrame.setText(str(self.j) + ' /')

            now = ptime.time()
            dt = now - lastTime
            lastTime = now
            if fps is None:
                fps = 1.0/dt
            else:
                s = np.clip(dt*3., 0, 1)
                fps = fps * (1-s) + (1.0/dt) * s
            self.fpsBox.setText('%0.2f fps' % fps)

        if self.j < self.n:     # It hasn't finished
            QtCore.QTimer.singleShot(0, self.updateWhileRec)

        else:                                           # The recording is over
            self.j = 0                                  # Reset counter
            self.recWidget.recButton.setChecked(False)
            self.liveview()

            if self.format == 'hdf5':

                # Saving parameters as data attributes in the HDF5 file
                dset = self.store_file[self.dataname]
                dset.attrs['Date'] = time.strftime("%Y-%m-%d")
                dset.attrs['Time'] = time.strftime("%H:%M:%S")
                attrs = []
                for ParName in self.p.getValues():
                    Par = self.p.param(str(ParName))
                    if not(Par.hasChildren()):
                        attrs.append((str(ParName), Par.value()))
                    else:
                        for sParName in Par.getValues():
                            sPar = Par.param(str(sParName))
                            if sPar.type() != 'action':
                                if not(sPar.hasChildren()):
                                    attrs.append((str(sParName), sPar.value()))
                                else:
                                    for ssParName in sPar.getValues():
                                        ssPar = sPar.param(str(ssParName))
                                        attrs.append((str(ssParName),
                                                      ssPar.value()))

                for item in attrs:
                    dset.attrs[item[0]] = item[1]

                self.store_file.close()

            elif self.format == 'tiff':

                os.chdir(self.recPath)
                tiff.imsave(self.recFilename + '.tiff', self.stack,
                            description=self.dataname, software='Tormenta')

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

    with CCD() as andor, \
            Laser(VFL, 'COM11') as redlaser, \
            Laser(Cobolt0601, 'COM4') as bluelaser, \
            Laser(Ventus, 'COM10') as greenlaser:

        print(andor.idn)
        print(redlaser.idn)
        print(bluelaser.idn)
        print(greenlaser.idn)

        win = TormentaGUI()
        win.show()

        app.exec_()