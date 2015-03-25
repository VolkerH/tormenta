# -*- coding: utf-8 -*-
"""
Created on Fri Feb  6 13:20:02 2015

@author: federico
"""

import pyqtgraph as pg
import numpy as np


class Grid():

    def __init__(self, viewBox, shape):

        self.showed = False
        self.vb = viewBox
        self.shape = shape

        self.yline1 = pg.InfiniteLine(pos=0.25*self.shape[0], pen='y')
        self.yline2 = pg.InfiniteLine(pos=0.50*self.shape[0], pen='y')
        self.yline3 = pg.InfiniteLine(pos=0.75*self.shape[0], pen='y')
        self.xline1 = pg.InfiniteLine(pos=0.25*self.shape[1], pen='y', angle=0)
        self.xline2 = pg.InfiniteLine(pos=0.50*self.shape[1], pen='y', angle=0)
        self.xline3 = pg.InfiniteLine(pos=0.75*self.shape[1], pen='y', angle=0)

    def update(self, shape):
        self.yline1.setPos(0.25*shape[0])
        self.yline2.setPos(0.50*shape[0])
        self.yline3.setPos(0.75*shape[0])
        self.xline1.setPos(0.25*shape[1])
        self.xline2.setPos(0.50*shape[1])
        self.xline3.setPos(0.75*shape[1])

    def toggle(self):

        if self.showed:
            self.hide()

        else:
            self.show()

    def show(self):
        self.vb.addItem(self.xline1)
        self.vb.addItem(self.xline2)
        self.vb.addItem(self.xline3)
        self.vb.addItem(self.yline1)
        self.vb.addItem(self.yline2)
        self.vb.addItem(self.yline3)
        self.showed = True

    def hide(self):
        self.vb.removeItem(self.xline1)
        self.vb.removeItem(self.xline2)
        self.vb.removeItem(self.xline3)
        self.vb.removeItem(self.yline1)
        self.vb.removeItem(self.yline2)
        self.vb.removeItem(self.yline3)
        self.showed = False


class Crosshair():

    def __init__(self, viewBox):

        self.showed = False

        self.vLine = pg.InfiniteLine(pos=0, angle=90, movable=False)
        self.hLine = pg.InfiniteLine(pos=0, angle=0,  movable=False)
        self.vb = viewBox

    def mouseMoved(self, evt):
        pos = evt
        if self.vb.sceneBoundingRect().contains(pos):
            mousePoint = self.vb.mapSceneToView(pos)
            self.vLine.setPos(mousePoint.x())
            self.hLine.setPos(mousePoint.y())

    def mouseClicked(self):
        try:
            self.vb.scene().sigMouseMoved.disconnect(self.mouseMoved)
        except:
            pass

    def toggle(self):

        if self.showed:
            self.hide()

        else:
            self.show()

    def show(self):
        self.vb.scene().sigMouseClicked.connect(self.mouseClicked)
        self.vb.scene().sigMouseMoved.connect(self.mouseMoved)
        self.vb.addItem(self.vLine, ignoreBounds=False)
        self.vb.addItem(self.hLine, ignoreBounds=False)
        self.showed = True

    def hide(self):
        self.vb.removeItem(self.vLine)
        self.vb.removeItem(self.hLine)
        self.showed = False


class ROI(pg.ROI):

    def __init__(self, shape, vb, *args, **kwargs):

        self.mainShape = shape

        pg.ROI.__init__(self, pos=(0.5 * shape[0] - 64, 0.5 * shape[1] - 64),
                        size=(128, 128), scaleSnap=True, translateSnap=True,
                        pen='y', *args, **kwargs)
        self.addScaleHandle((1, 0), (0, 1), lockAspect=True)
        vb.addItem(self)

        self.label = pg.TextItem()
        self.label.setPos(self.pos())
        self.label.setText('128x128')

        self.sigRegionChanged.connect(self.updateText)

        vb.addItem(self.label)

    def updateText(self):
        self.label.setPos(self.pos())
        size = np.round(self.size()).astype(np.int)
        self.label.setText('{}x{}'.format(size[0], size[1]))

    def hide(self, *args, **kwargs):
        super(ROI, self).hide(*args, **kwargs)
        self.label.hide()