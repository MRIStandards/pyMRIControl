'''
Created on Nov. 7, 2023
Class to control TechMag MRI system along with associated controls including temperature, interlocks etc
#    Anaconda 3 with Python 3.7    (64 bit, Python, PyQT5, Numpy, Scipy, Pillow )
#    pyqtgraph Version: 0.10.0     (for plotting and image windows)
***To Do

#"  src\pyuic5MRLab.bat src\pico5000MRI.ui -o src\pico5000MRIGui.py  " from system shell to regenerate command input window        
@author: stephen russek
Modified 20231119
'''
#
# Copyright (C) 2018-2022 Pico Technology Ltd. See LICENSE file for terms.
#
# PS5000A BLOCK MODE EXAMPLE
# This example opens a 5000a driver device, sets up two channels and a trigger then collects a block of data.
# This data is then plotted as mV against time in ns.
import sys
import os    #operating system file/directory names 
import ctypes
import numpy as np
from ps5000a import ps5000a as ps
import matplotlib.pyplot as plt
from PyQt5.Qt import PYQT_VERSION_STR
from PyQt5.QtCore import  Qt, QPoint, QTimer
from PyQt5.QtGui import  QFont, QColor, QPainter, QPixmap, QTextOption, QScreen, QPen, QTextCursor
from PyQt5.QtWidgets import QApplication, QMainWindow,  QWidget, QProgressDialog, QInputDialog, QColorDialog, QLineEdit, QFileDialog, QAction, QTextEdit, QToolTip, QStatusBar, QMenuBar, QMessageBox, QVBoxLayout
from pyqtgraph.graphicsItems.ScatterPlotItem import ScatterPlotItem
import pyqtgraph as pg
from picosdk.functions import adc2mV, assert_pico_ok, mV2adc
from pico5000MRIGui import Ui_pico5000MRI


class pico5000MRI(QMainWindow):
  'Main form for setting up MRI pulse sequences'
  def __init__(self , parent = None):
    super(pico5000MRI, self).__init__()
    self.ui = Ui_pico5000MRI()
    self.ui.setupUi(self)
    self.setWindowTitle('MRI picoscope')
    self.picoPlot=self.ui.picoPlot
    self.picoPlot.show()
    self.ui.pbPicoCapture.clicked.connect(self.picoCapture)
    self.ui.pbPauseContinue.clicked.connect(self.pauseContinue)
    self.ui.pbSetupPS.clicked.connect(self.setupPicoscope)
    self.pauseCapture=False     #flage to pause scope capture
    self.chandle = ctypes.c_int16()
    self.status = {}

    # Open 5000 series PicoScope # Resolution set to 12 Bit
    resolution =ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_12BIT"]
    # Returns handle to self.chandle for use in future API functions
    self.status["openunit"] = ps.ps5000aOpenUnit(ctypes.byref(self.chandle), None, resolution)
    
    try:
        assert_pico_ok(self.status["openunit"])
    except: # PicoNotOkError:
    
        powerStatus = self.status["openunit"]
    
        if powerStatus == 286:
            self.status["changePowerSource"] = ps.ps5000aChangePowerSource(self.chandle, powerStatus)
        elif powerStatus == 282:
            self.status["changePowerSource"] = ps.ps5000aChangePowerSource(self.chandle, powerStatus)
        else:
            raise
    
        assert_pico_ok(self.status["changePowerSource"])
        
    #setup gui
    self.p1=pg.mkPen('r', width=1)
    self.p2=pg.mkPen('g', width=1)
    self.p3=pg.mkPen('c', width=1)
    self.p4=pg.mkPen('y', width=1)
    self.picoPlot.setLabel('bottom','Time', units='s')
    self.picoPlot.setLabel('left', 'Signal', units='V')
    self.infx1 = pg.InfiniteLine(movable=True, angle=90, label='t1={value:0.6f}', 
        labelOpts={'position':0.1, 'color': (200,200,100), 'fill': (200,200,200,50), 'movable': True})
    self.infx2 = pg.InfiniteLine(movable=True, angle=90, label='t2={value:0.6f}', 
        labelOpts={'position':0.9, 'color': (200,100,100), 'fill': (200,200,200,50), 'movable': True})
    self.infy1 = pg.InfiniteLine(movable=True, angle=0, pen=(0, 0, 200),  hoverPen=(0,200,0), label='y1={value:0.1f}', 
        labelOpts={'color': (200,0,0), 'movable': True, 'fill': (0, 0, 200, 100)})
    self.infy2 = pg.InfiniteLine(movable=True, angle=0, pen=(0, 0, 200),  hoverPen=(0,200,0), label='y2={value:0.1f}', 
        labelOpts={'color': (200,0,0), 'movable': True, 'fill': (0, 0, 200, 100)})
    self.infx1.setValue(0.0)
    self.infx2.setValue(0.0)
    self.picoPlot.addItem(self.infx1)
    self.picoPlot.addItem(self.infx2)
    self.infx1.sigPositionChanged.connect(self.updateMarkerLabel)
    self.infx2.sigPositionChanged.connect(self.updateMarkerLabel)
    self.preTriggerPoints = 1000
    self.postTriggerPoints = 5000
    self.ui.sbPreTriggerPoints.setValue(self.preTriggerPoints)
    self.ui.sbPostTriggerPoints.setValue(self.postTriggerPoints)
    self.channelARange="PS5000A_5V"
    self.channelBRange="PS5000A_5V"
    self.channelCRange="PS5000A_5V"
    self.channelDRange="PS5000A_5V"
    self.timebase = 625
    if self.timebase>2:
        self.SampleTime=2*(self.timebase-2)/(125*10**6)
    else:
        self.SampleTime=self.timebase/10**9    
    self.ui.dspboxSampleTime.setValue(self.SampleTime*1E6)
    self.setupPicoscope()
    
  def setupPicoscope(self):
        self.preTriggerPoints=self.ui.sbPreTriggerPoints.value()
        self.postTriggerPoints=self.ui.sbPostTriggerPoints.value()
        # Set up channel A, handle = self.chandle
        channel = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"]
        coupling_type = ps.PS5000A_COUPLING["PS5000A_DC"]
        self.chARange = ps.PS5000A_RANGE[self.channelARange]
        self.status["setChA"] = ps.ps5000aSetChannel(self.chandle, channel, 1, coupling_type, self.chARange, 0)
        assert_pico_ok(self.status["setChA"])
        
        # Set up channel B, handle = self.chandle
        channel = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_B"]
        coupling_type = ps.PS5000A_COUPLING["PS5000A_DC"]
        self.chBRange = ps.PS5000A_RANGE[self.channelBRange]
        self.status["setChB"] = ps.ps5000aSetChannel(self.chandle, channel, 1, coupling_type, self.chBRange, 0)
        assert_pico_ok(self.status["setChB"])
        
        # Set up channel C, handle = self.chandle
        channel = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_C"]
        coupling_type = ps.PS5000A_COUPLING["PS5000A_DC"]
        self.chCRange = ps.PS5000A_RANGE[self.channelCRange]
        self.status["setChC"] = ps.ps5000aSetChannel(self.chandle, channel, 1, coupling_type, self.chCRange, 0)
        assert_pico_ok(self.status["setChC"])
         
        # Set up channel D  ***RF***, handle = self.chandle
        channel = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_D"]
        coupling_type = ps.PS5000A_COUPLING["PS5000A_DC"]
        self.chDRange = ps.PS5000A_RANGE[self.channelDRange]
        self.status["setChD"] = ps.ps5000aSetChannel(self.chandle, channel, 1, coupling_type, self.chDRange, 0)
        assert_pico_ok(self.status["setChD"])
           
        self.maxADC = ctypes.c_int16()
        self.status["maximumValue"] = ps.ps5000aMaximumValue(self.chandle, ctypes.byref(self.maxADC))
        assert_pico_ok(self.status["maximumValue"])
        
        # Set up single trigger
#        PICO_STATUS ps5000aSetSimpleTrigger(int16_t handle,int16_t enable,PS5000A_CHANNEL source,int16_t threshold,PS5000A_THRESHOLD_DIRECTION direction,uint32_t delay,int16_t autoTrigger_ms)

        source = ps.PS5000A_CHANNEL["PS5000A_EXTERNAL"]
        threshold = int(mV2adc(500,self.chARange, self.maxADC))
        direction = 2   # PS5000A_RISING = 2
        delay = 0   #delay in s after trigger before acquiring
        autoTrigger = 10000    #0 means wait, otherwise trigger will occur in autoTrigger ms, note if set to 0, will hang up waiting for a trigger
        self.status["trigger"] = ps.ps5000aSetSimpleTrigger(self.chandle, 1, source, threshold, direction, delay, autoTrigger)        #
        assert_pico_ok(self.status["trigger"])
        
        # Set number of pre and post trigger samples to be collected
  
        self.maxSamples = self.preTriggerPoints + self.postTriggerPoints
        
        # Get self.timebase information
        # Warning: When using this example it may not be possible to access all Timebases as all channels are enabled by default when opening the scope.  
        # To access these Timebases, set any unused analogue channels to off.
        # handle = self.chandle
        self.SampleTime=self.ui.dspboxSampleTime.value()*1E-6
        self.timebase = int(1E6*self.SampleTime*125/2+2) 
        if self.timebase>2:
            self.SampleTime=2*(self.timebase-2)/(125*10**6)
        else:
            self.SampleTime=self.timebase/10**9    
        self.ui.dspboxSampleTime.setValue(self.SampleTime*1E6)
        self.ui.leAcquisitionTime.setText('{:6.3f}'.format(self.SampleTime*self.maxSamples*1000))
        #timebase
            # 0 => 1 ns
            # 1 => 2 ns
            # 2 => 4 ns
            # > 2 (timebase - 2) / 125,000,000
            # For example: 3 => 8 ns, 4 => 16 ns, 5 => 24 ns up to 34s
 
        # noSamples = self.maxSamples
        # pointer to timeIntervalNanoseconds = ctypes.byref(self.timeIntervalns)
        # pointer to maxSamples = ctypes.byref(returnedMaxSamples)
        # segment index = 0
        self.timeIntervalns = ctypes.c_float()
        self.returnedMaxSamples = ctypes.c_int32()
        self.status["getTimebase2"] = ps.ps5000aGetTimebase2(self.chandle, self.timebase, self.maxSamples, ctypes.byref(self.timeIntervalns), ctypes.byref(self.returnedMaxSamples), 0)
        assert_pico_ok(self.status["getTimebase2"])

        
  def picoCapture(self):
        if self.pauseCapture:
            return
        self.status["runBlock"] = ps.ps5000aRunBlock(self.chandle, self.preTriggerPoints, self.postTriggerPoints, self.timebase, None, 0, None, None)
        assert_pico_ok(self.status["runBlock"])
        
        # Check for data collection to finish using ps5000aIsReady
        ready = ctypes.c_int16(0)
        check = ctypes.c_int16(0)
        while ready.value == check.value:
            self.status["isReady"] = ps.ps5000aIsReady(self.chandle, ctypes.byref(ready))
        
        
        # Create buffers ready for assigning pointers for data collection
        bufferAMax = (ctypes.c_int16 * self.maxSamples)()
        bufferAMin = (ctypes.c_int16 * self.maxSamples)() # used for downsampling which isn't in the scope of this example
        bufferBMax = (ctypes.c_int16 * self.maxSamples)()
        bufferBMin = (ctypes.c_int16 * self.maxSamples)() # used for downsampling which isn't in the scope of this example
        bufferCMax = (ctypes.c_int16 * self.maxSamples)()
        bufferCMin = (ctypes.c_int16 * self.maxSamples)() # used for downsampling which isn't in the scope of this example
        bufferDMax = (ctypes.c_int16 * self.maxSamples)()
        bufferDMin = (ctypes.c_int16 * self.maxSamples)() # used for downsampling which isn't in the scope of this example
        
        # Set data buffer location for data collection from channel A
        source = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"]
        self.status["setDataBuffersA"] = ps.ps5000aSetDataBuffers(self.chandle, source, ctypes.byref(bufferAMax), ctypes.byref(bufferAMin), self.maxSamples, 0, 0)
        assert_pico_ok(self.status["setDataBuffersA"])
        
        # Set data buffer location for data collection from channel B
        source = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_B"]
        self.status["setDataBuffersB"] = ps.ps5000aSetDataBuffers(self.chandle, source, ctypes.byref(bufferBMax), ctypes.byref(bufferBMin), self.maxSamples, 0, 0)
        assert_pico_ok(self.status["setDataBuffersB"])
        # Set data buffer location for data collection from channel C
        source = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_C"]
        self.status["setDataBuffersC"] = ps.ps5000aSetDataBuffers(self.chandle, source, ctypes.byref(bufferCMax), ctypes.byref(bufferCMin), self.maxSamples, 0, 0)
        assert_pico_ok(self.status["setDataBuffersC"])
        # Set data buffer location for data collection from channel D
        source = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_D"]
        self.status["setDataBuffersD"] = ps.ps5000aSetDataBuffers(self.chandle, source, ctypes.byref(bufferDMax), ctypes.byref(bufferDMin), self.maxSamples, 0, 0)
        assert_pico_ok(self.status["setDataBuffersD"])
        
        # create overflow loaction
        overflow = ctypes.c_int16()
        # create converted type maxSamples
        cmaxSamples = ctypes.c_int32(self.maxSamples)
        
        # Retried data from scope to buffers assigned above
        # handle = self.chandle
        # start index = 0
        # pointer to number of samples = ctypes.byref(cmaxSamples)
        # downsample ratio = 0
        # downsample ratio mode = PS5000A_RATIO_MODE_NONE
        # pointer to overflow = ctypes.byref(overflow))
        self.status["getValues"] = ps.ps5000aGetValues(self.chandle, 0, ctypes.byref(cmaxSamples), 0, 0, 0, ctypes.byref(overflow))
        assert_pico_ok(self.status["getValues"])
        
        
        # convert ADC counts data to mV
        adc2VChAMax =  np.asarray(adc2mV(bufferAMax, self.chARange, self.maxADC))/1000
        adc2VChBMax =  np.asarray(adc2mV(bufferBMax, self.chBRange, self.maxADC))/1000
        adc2VChCMax =  np.asarray(adc2mV(bufferCMax, self.chCRange, self.maxADC))/1000
        adc2VChDMax =  np.asarray(adc2mV(bufferDMax, self.chDRange, self.maxADC))/1000
        self.waveformInfo='Waveform points={}, timebase={}'.format(len(adc2VChAMax),self.timebase)
        # Create time data in s
        time = np.linspace(0, (cmaxSamples.value - 1) * self.timeIntervalns.value, cmaxSamples.value)/1E9
        time-=self.preTriggerPoints*self.SampleTime #shift so t=0 corresponds to trigger
        self.picoPlot.clear()
        self.picoPlot.addItem(self.infx1)
        self.picoPlot.addItem(self.infx2)
        self.ui.picoPlot.plot(time, adc2VChAMax, pen=self.p1, width=2, name='Gx')
        self.ui.picoPlot.plot(time, adc2VChBMax, pen=self.p2, width=2, name='Gy')
        self.ui.picoPlot.plot(time, adc2VChCMax, pen=self.p3, width=2, name='Gz')
        self.ui.picoPlot.plot(time, adc2VChDMax, pen=self.p4, width=2, name='RF')
        self.ui.picoPlot.addLegend()
        self.ui.leMessages.setText(self.waveformInfo+', dt(ms)={:6.3f}'.format(1000*(self.infx2.value()-self.infx1.value())))
        # Stop the scope # handle = self.chandle
        self.status["stop"] = ps.ps5000aStop(self.chandle)
        assert_pico_ok(self.status["stop"])
        
  def pauseContinue(self):
      self.pauseCapture=not self.pauseCapture
      if self.pauseCapture:
          self.ui.pbPauseContinue.setStyleSheet("background-color: rgb(200, 50, 50) ")
      else:
          self.ui.pbPauseContinue.setStyleSheet("background-color: rgb(50, 200, 50)")
      
  def updateMarkerLabel(self):
        self.ui.leMessages.setText(self.waveformInfo+', dt(ms)={:6.3f}'.format(1000*(self.infx2.value()-self.infx1.value())))
               
  def closePicoscope(self):    
        # Close unit Disconnect the scope
        # handle = self.chandle
        self.status["close"]=ps.ps5000aCloseUnit(self.chandle)
        assert_pico_ok(self.status["close"])
        
        # display self.status returns
        #print(self.status)
        print("PicoScope closed")
  def closeEvent(self,event):
    self.closePicoscope()
        
#Useful for debugging Qt applications where the app closes without giving error message
sys._excepthook = sys.excepthook 
def exception_hook(exctype, value, traceback):
    print("Missed Exception:", exctype, value, traceback)
    #self.closePicoscope()
    sys._excepthook(exctype, value, traceback) 
    sys.exit(1) 
#*******
sys.excepthook = exception_hook       
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setStyleSheet("QWidget{font-size: 8pt;}") 
    main =pico5000MRI()
    main.show()
    sys.exit(app.exec_())    