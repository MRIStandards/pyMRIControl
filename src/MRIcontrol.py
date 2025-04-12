'''
Created on Nov. 7, 2023
Class to control TechMag MRI system along with associated controls including temperature, picoscope, interlocks etc
#    Anaconda 3 with Python 3.7    (64 bit, Python, PyQT5, Numpy, Scipy, Pillow )
#    pyqtgraph Version: 0.10.0     (for plotting and image windows)
***To Do
#"  src\pyuic5.bat src\MRIcontrol.ui -o src\MRIcontrolGui.py  " from system shell to regenerate command input window
#"  src\pyuic5MRLab.bat src\MRIcontrol.ui -o src\MRIcontrolGui.py  " from system shell to regenerate command input window        
@author: stephen russek


Important Conventions:
**************All parameters are stored in SI units m,s,Tesla,°C,A, V;  however display values can be in convenience units mm, ms, ...******************

Program loads a .tnt file, modifies it, runs it or puts it into a queue/recipe
Safety limits on the RF and gradient strength are embedded in the .tnt file 
Pulse sequence files must contain standard parameters and tables to allow the pulse sequence to be recognized and modified.

To add a protocol, 
    1. write basic TNMR sequence, 
    2. save in StandardSequenceDirectory with filename=desired protocol name, 
    3. add protocolName to self.protocolList, 
    4. make a setup dictionary for the new pulse sequence
    5. make custom processing method for the new pulse sequence
    



'''

modDate='2024-00-11'      #Last modification date

import sys
import os    #operating system file/directory names 
import subprocess
import re #regular expressions
import time
from winreg import *       #for accessing shared info via windows registry, used to talk to screen saver 
from datetime import datetime, timedelta
import numpy as np
from scipy import constants
from PyQt5.Qt import PYQT_VERSION_STR
from PyQt5.QtCore import  Qt, QPoint, QTimer
from PyQt5.QtGui import  QFont, QColor, QPainter, QPixmap, QTextOption, QScreen, QPen, QTextCursor
from PyQt5.QtWidgets import QApplication, QMainWindow,  QWidget, QProgressDialog, QInputDialog, QColorDialog, QLineEdit, QFileDialog, QAction, QTextEdit, QToolTip, QStatusBar, QMenuBar, QMessageBox, QVBoxLayout
from pyqtgraph.graphicsItems.ScatterPlotItem import ScatterPlotItem
import pyqtgraph as pg
import pyqtgraph.exporters
from MRIcontrolGui import Ui_MRIcontrol     #Main PyQT GUI for this application
from numpy import NaN
from TNMRmri import TNMR       #contains code to control TNMR software from Python
from TNMRviewer import TNMRviewer #Class to display images from unpacked .tnt files
from ps5000aMRI import pico5000MRI      #create py picoscope
import pyvisa       #Labview code to control other instruments including scopes, chillers, etc
import lmfit        #Used for nonlinear least squares fitting
import  dampedSin, multiExp  #fitting modules for NMR data based on  lmfit
#from pyasn1_modules.rfc3852 import AttributeCertificateInfoV1



class MRIcontrol(QMainWindow):
  'Main form for setting up MRI pulse sequences'
  def __init__(self , parent = None):
    super(MRIcontrol, self).__init__()
    self.ui = Ui_MRIcontrol()
    self.ui.setupUi(self)
    frameGm = self.frameGeometry()
    topLeftPoint = QApplication.desktop().availableGeometry().topLeft()
    frameGm.moveTopLeft(topLeftPoint)
    self.move(frameGm.topLeft())
    self.modDate=modDate
    self.setWindowTitle('MRI Control: ModDate=' +  self.modDate)
    #Physical Constants
    self.GammaPMHzperT=constants.physical_constants["proton gyromag. ratio over 2 pi"][0]   #in MHz/T 
    self.GammaPHzperT=1E6*constants.physical_constants["proton gyromag. ratio over 2 pi"][0]   #in Hz/T 
    self.GammaWaterProtonRadperT=constants.physical_constants["proton gyromag. ratio"][0]*(1-constants.physical_constants["proton mag. shielding correction"][0])                                                                                
    self.Gamma=self.GammaWaterProtonRadperT
    self.Gammaf=self.Gamma/2/np.pi
    self.TrueOrFalse=['True', 'False']
    self.ONorOFF=['ON', 'OFF']
#************Shim parameters*****************    
    self.initialShims=['zero', 'CurrentShims']
    self.currentShims=( 'Gx', 'Gy', 'Gz','C2','S2','Z2', 'ZX','ZY') #8 MRI shims
    self.currentShimValues={'Gx':0, 'Gy':0, 'Gz':0,'C2':0,'S2':0,'Z2':0, 'ZX':0,'ZY':0}
    self.shimLabels={'Gx':self.ui.spGx, 'Gy':self.ui.spGy, 'Gz':self.ui.spGz,'C2':self.ui.spC2,'S2':self.ui.spS2,'Z2':self.ui.spZ2, 'ZX':self.ui.spZX,'ZY':self.ui.spZY}
    self.autoShimList='Z2, ZX, ZY, Gx, Gy, Gz, C2, S2'
    self.quickShimList='Z2, Gx, Gy, Gz'
    self.shimValue=np.zeros(len(self.currentShims))     #obsolete 
    self.shimmingInProgress=False
    self.ShimUnits=[]
    self.pltShimUnits=self.ui.pltShimUnits
    self.ShimDelay ="1s"
    self.ShimPrecision = 0.05
    self.ShimLockorFid = 1
    self.ShimStep = 100
    self.maxTecmagDACcount=2**15-4000        #maximum DAC count for tecmag receive channel, if signal is above this level it can be saturated. Currently set at 28768
    self.blRegionStart=0.9       #region of spectra used to calculate baseline, assumes all data beyond self.blRegionStart and below self.blRegionStart should be zero!!
    self.blRegionStop=0.99# we do not look at last data points in TechMag FIDs because they are arbitrarily set to 0
    self.subtractFIDBackground=True 
#******B0 compensation and Gradient PreEmphasis labels, mirrors values
    self.B0CompLabels={'DC.bx':self.ui.leDCbx, 'A0.bx':self.ui.leA0bx, 'A1.bx':self.ui.leA1bx,'A2.bx':self.ui.leA2bx,'A3.bx':self.ui.leA3bx,'A4.bx':self.ui.leA4bx, 'A5.bx':self.ui.leA5bx,'T1.bx':self.ui.leT1bx,'T2.bx':self.ui.leT2bx,'T3.bx':self.ui.leT3bx,'T4.bx':self.ui.leT4bx,'T5.bx':self.ui.leT5bx,\
                       'DC.by':self.ui.leDCby, 'A0.by':self.ui.leA0by, 'A1.by':self.ui.leA1by,'A2.by':self.ui.leA2by,'A3.by':self.ui.leA3by,'A4.by':self.ui.leA4by, 'A5.by':self.ui.leA5by,'T1.by':self.ui.leT1by,'T2.by':self.ui.leT2by,'T3.by':self.ui.leT3by,'T4.by':self.ui.leT4by,'T5.by':self.ui.leT5by,\
                       'DC.bz':self.ui.leDCbz, 'A0.bz':self.ui.leA0bz, 'A1.bz':self.ui.leA1bz,'A2.bz':self.ui.leA2bz,'A3.bz':self.ui.leA3bz,'A4.bz':self.ui.leA4bz, 'A5.bz':self.ui.leA5bz,'T1.bz':self.ui.leT1bz,'T2.bz':self.ui.leT2bz,'T3.bz':self.ui.leT3bz,'T4.bz':self.ui.leT4bz,'T5.bz':self.ui.leT5bz}
    self.gradPreEmphasisLabels={'DC.x':self.ui.leDCx, 'A0.x':self.ui.leA0x, 'A1.x':self.ui.leA1x,'A2.x':self.ui.leA2x,'A3.x':self.ui.leA3x,'A4.x':self.ui.leA4x, 'A5.x':self.ui.leA5x,'T1.x':self.ui.leT1x,'T2.x':self.ui.leT2x,'T3.x':self.ui.leT3x,'T4.x':self.ui.leT4x,'T5.x':self.ui.leT5x,\
                       'DC.y':self.ui.leDCy, 'A0.y':self.ui.leA0y, 'A1.y':self.ui.leA1y,'A2.y':self.ui.leA2y,'A3.y':self.ui.leA3y,'A4.y':self.ui.leA4y, 'A5.y':self.ui.leA5y,'T1.y':self.ui.leT1y,'T2.y':self.ui.leT2y,'T3.y':self.ui.leT3y,'T4.y':self.ui.leT4y,'T5.y':self.ui.leT5y,\
                       'DC.z':self.ui.leDCz, 'A0.z':self.ui.leA0z, 'A1.z':self.ui.leA1z,'A2.z':self.ui.leA2z,'A3.z':self.ui.leA3z,'A4.z':self.ui.leA4z, 'A5.z':self.ui.leA5z,'T1.z':self.ui.leT1z,'T2.z':self.ui.leT2z,'T3.z':self.ui.leT3z,'T4.z':self.ui.leT4z,'T5.z':self.ui.leT5z}
    self.B0CompZeroAmpl=('A0.bx', 'A1.bx','A2.bx','A3.bx','A4.bx', 'A5.bx','A0.by', 'A1.by','A2.by','A3.by','A4.by', 'A5.by','A0.bz', 'A1.bz','A2.bz','A3.bz','A4.bz', 'A5.bz','A0.bz', 'A1.bz','A2.bz','A3.bz','A4.bz', 'A5.bz') #terms to zero to turn off B0comp                   
    self.gradPreEmphasisZeroAmpl=('A0.x', 'A1.x','A2.x','A3.x','A4.x', 'A5.x','A0.y', 'A1.y','A2.y','A3.y','A4.y', 'A5.y','A0.z', 'A1.z','A2.z','A3.z','A4.z', 'A5.z','A0.z', 'A1.z','A2.z','A3.z','A4.z', 'A5.z')  #terms to zero to turn off B0comp
#*******Dictionaries to setup different protocols*************
    #Note the order is important in the protocol list since if it finds latter text in the filename it will supersede earlier elements in the list
    self.protocolList=('none', 'SCOUT', 'ShimFIDHP', 'RFTxCal','GEMS', 'SEMS', 'SEMS2', 'SEMS_IR', 'PGSE_Dif', 'T1IR_NMR', "CPMG_NMR",'T2SE_NMR', 'HPnutation', 'FID90ECC', 'scanECCParam') # in development 'ShimFIDSS','GEMS_IR',
    self.ui.cbProtocol.clear()
    self.ui.cbProtocol.addItems(self.protocolList)      #Add protocol items to combobox
    self.nonesetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':False,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':False,\
        'Slices':False,'Averages':False,'PhaseEncodes':False,'Parameters':False,'RFpw':False,'ReceiverGain':False,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':''}  
    self.SCOUTsetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':False,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':False,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':False,'RFpw':False,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':True,'SliceSpacing':False,'SlicePositions':False,'FoVro':True,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':0,'GpSign':1,'GrSign':1,'GrrSign':1,'GsSign':1,'GsrSign':-1, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'processScout(nRF=-1, raw=False)', 'OptionsTab':self.ui.SCOUTOptions, 'ProtocolDescription':'Fast spin echo SCOUT that acquires axial, coronal, and sagittal images for slice planning'}
    self.ShimFIDHPsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Simple hard RF pulse (HP) with subsequent FID acquisition, for determination of center frequency, frequency width, and for shimming'} 
    self.ShimFIDSSsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':True,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Slice select SINC RF pulse with subsequent FID acquisition'} 
    self.FID90ECCsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':True,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'processFIDECC()', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'RO Gradient pulse preceding hard RF pulse with subsequent FID acquisition, used for B0 and eddy current compensation (ECC)'} 
    self.scanECCParamsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':True,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'RO Gradient pulse preceding hard RF pulse with subsequent FID acquisition, scans ECC parameter to maximize signal'} 
    self.RFTxCalsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':False,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'none', 'DisplayImages':False, 'PostProcessRoutine':'processRFTxCal()', 'OptionsTab':self.ui.RFCalOptions,'ProtocolDescription':'Hard RF pulse with stepped RF Attn array with subsequent FID acquisition to calibrate RF transmit field'}   
    self.GEMSsetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':True,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':True,'FoVro':True,'GradOrientation':True,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':True,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':0,'GpSign':-1,'GrSign':1,'GrrSign':-1,'GsSign':1,'GsrSign':-1, '4DParam':'TE', 'DisplayImages':True, 'PostProcessRoutine':'', 'OptionsTab':self.ui.GEMSOptions, 'ProtocolDescription':'Gradient Echo MultiSlice with SINC frequency-stepped slice select,opt. stepped TE array'} 
    self.GEMS_IRsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':False,'PhaseEncodes':False,'Parameters':False,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':True,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':True,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':True, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':0,'GpSign':-1,'GrSign':1,'GrrSign':-1,'GsSign':1,'GsrSign':-1, '4DParam':'TI', 'DisplayImages':True, 'PostProcessRoutine':'', 'ProtocolDescription':'Gradient Echo MultiSlice with a preparatory 180 inversion pulse, stepped TI array for T1 measurement '}         
    self.SEMSsetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':True,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':True,'FoVro':True,'GradOrientation':True,'RFAttn90':True,'RFAttn180':True,'XVoxSize':False, 'TE':True,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':1,'GpSign':-1,'GrSign':-1,'GrrSign':1,'GsSign':1,'GsrSign':-1, '4DParam':'TE', 'DisplayImages':True, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Spin Echo MultiSlice with SINC frequency-stepped slice select,opt. stepped TE array. SEMS has readout rewind and phase encode gradients at the beginning just after Slice Select'}
    self.SEMS2setup={'TMRFobserve':True,'DwellTime':False,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':True,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':True,'FoVro':True,'GradOrientation':True,'RFAttn90':True,'RFAttn180':True,'XVoxSize':False, 'TE':True,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':1,'GpSign':-1,'GrSign':-1,'GrrSign':-1,'GsSign':1,'GsrSign':-1, '4DParam':'TE', 'DisplayImages':True, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Spin Echo MultiSlice with SINC frequency-stepped slice select,opt. stepped TE array. SEMS2 has readout rewind and phase encode gradients at the end just before readout'}  
    self.SEMS_IRsetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':True,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':True,'FoVro':True,'GradOrientation':True,'RFAttn90':True,'RFAttn180':True,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':True, 'TipAngle':False,'Bvalue':False,'GspoilSign':1,'GdpSign':1,'GpSign':-1,'GrSign':-1,'GrrSign':1,'GsSign':1,'GsrSign':-1, '4DParam':'TI', 'DisplayImages':True, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Spin Echo MultiSlice with a preparatory 180 inversion pulse, stepped TI array for T1 measurement'}  
    self.T1IR_NMRsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':True, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'TI', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'NMR sequence using RF hard pulse with a preparatory 180 inversion pulse, no gradients, stepped TI array for T1 measurement'}
    self.CPMG_NMRsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'TE', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':''}
    self.T2SE_NMRsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':True,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'TE', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':''}  
    self.HPnutationsetup={'TMRFobserve':True,'DwellTime':True,'LastDelay':True,'TNMRAcqTime':True,'TNMRSW':True,'TNMRnAcqPoints':True,\
        'Slices':False,'Averages':True,'PhaseEncodes':False,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':False,'FoVro':False,'GradOrientation':False,'RFAttn90':False,'RFAttn180':False,'XVoxSize':False, 'TE':True,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':False,'GspoilSign':0,'GdpSign':0,'GpSign':0,'GrSign':0,'GrrSign':0,'GsSign':0,'GsrSign':0, '4DParam':'TE', 'DisplayImages':False, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':''}        
    self.PGSE_Difsetup={'TMRFobserve':True,'DwellTime':False,'LastDelay':True,'TNMRAcqTime':False,'TNMRSW':False,'TNMRnAcqPoints':True,\
        'Slices':True,'Averages':True,'PhaseEncodes':True,'Parameters':True,'RFpw':True,'ReceiverGain':True,'GradientOrientation':False,\
        'SliceThickness':False,'SliceSpacing':False,'SlicePositions':True,'FoVro':True,'GradOrientation':True,'RFAttn90':True,'RFAttn180':True,'XVoxSize':False, 'TE':False,\
        'TR':False,'TI':False, 'TipAngle':False,'Bvalue':True,'GspoilSign':1,'GdpSign':1,'GpSign':-1,'GrSign':-1,'GrrSign':-1,'GsSign':1,'GsrSign':-1, '4DParam':'bValue', 'DisplayImages':True, 'PostProcessRoutine':'', 'OptionsTab':self.ui.SEMSOptions, 'ProtocolDescription':'Pulsed Gradient Spin Echo for diffusion weighting with stepped gradient strengths and b-values'} 
#******dictionary relating scan orientation to Tecmag 'XYZ' orientation string 
    self.scanOrientation={'XZY':'Coronal RO=X, PE=Z','ZXY':'Coronal RO=Z, PE=X',\
                                      'ZYX':"Sagittal RO=Z, PE=Y", 'YZX':'Sagittal RO=Y, PE=Z',\
                                      'XYZ':'Axial RO=X, PE=Y', 'YXZ':'Axial RO=Y, PE=X',\
                                      'Coronal RO=X, PE=Z':'XZY', 'Coronal RO=Z, PE=X':'ZXY',\
                                      "Sagittal RO=Z, PE=Y":'ZYX', 'Sagittal RO=Y, PE=Z':'YZX',\
                                      'Axial RO=X, PE=Y':'XYZ', 'Axial RO=Y, PE=X':'YXZ'}
     
    self.NMRfileName=''     #file name for current pulse sequence
    self.recipeFileName=''  #filename for current recipe if a recipe is opened or saved.  Used as a director to safe monitor and message data
    self.imw=TNMRviewer(self)      #create an imageWIndow to display acquired image data
    self.dataMagPlot=self.ui.pltRawData
    self.paramColor='background-color: rgb(255, 210, 220)'      #color for parameters labels
    self.defaulLabelColor='background-color: rgb(240, 240, 240)'      #color for parameters labels
    #vertical light yellow lines for plot markers
    self.infx1 = pg.InfiniteLine(movable=True, angle=90,pen=(255,255,204), label='x1={value:0.1f}', 
                labelOpts={'position':0.1, 'color': (200,200,100), 'fill': (200,200,200,50), 'movable': True})  
    self.infx2 = pg.InfiniteLine(movable=True, angle=90, pen=(255,255,150),label='x2={value:0.1f}', 
                labelOpts={'position':0.9, 'color': (200,100,100), 'fill': (200,200,200,50), 'movable': True})
    #horizontal blue lines for plot markers
    self.infy1 = pg.InfiniteLine(movable=True, angle=0, pen=(0, 0, 200),  hoverPen=(0,200,0), label='y1={value:0.1f}', 
                labelOpts={'color': (200,0,0), 'movable': True, 'fill': (0, 0, 200, 100)})
    self.infy2 = pg.InfiniteLine(movable=True, angle=0, pen=(0, 0, 200),  hoverPen=(0,200,0), label='y2={value:0.1f}', 
                labelOpts={'color': (200,0,0), 'movable': True, 'fill': (0, 0, 200, 100)})
    self.ypen=pg.mkPen('y', width=2)
    self.rpen=pg.mkPen('r', width=2)
    self.gpen=pg.mkPen('g', width=2)
    self.bpen=pg.mkPen('b', width=2)
    self.wpen=pg.mkPen('w', width=2)
    self.kpen=pg.mkPen('k', width=2)
    self.open=pg.mkPen(pg.mkColor(255,125,15), width=2)
    self.slicepen=pg.mkPen('g', width=1)
    self.msgBox=QMessageBox()
    self.msgBox.setIcon(QMessageBox.Warning)
    self.msgBox.setWindowTitle('TNMR initialization')
    self.msgBox.setText("Opening TNMR and NMR RF Control, please be patient...")
    self.msgBox.setWindowModality(Qt.NonModal)
    self.msgBox.show()
    try:
        self.TNMR=TNMR(self)    #create a TNMR console
        self.message('TNMR console open:', bold=True, ctime=True, color='blue')
        self.getShimValues()
        #subprocess.call(r"C:\TNMR\bin\RFControl.exe")       #RF control routine to enable receive amps
    except:
        self.message("Cannot open TNMR console")
    self.msgBox.hide()
    self.TNMRdirectoryDefault=r"C:\TNMR\data"       #default starting directory
    self.TNMRdirectory=self.TNMRdirectoryDefault        #current directory of interest, will follow pathname and directory of recently opened files
    self.studyDirectory=self.TNMRdirectoryDefault
    self.closeActiveFile=True       #flag to close TNMR active file before opening a new one
    self.recipeRunning=False        #flag to indicate if recipe (queue) is running
    self.recipeAbort=False          #flag to stop/ abort current TNMR pulse sequence and recipe
    self.TNMRjustFinished=False     #flag to indicate that the pulse sequence just finished
    self.TNMRbusyOld=False          #State of TNMR on previous inquiry
    self.UpdateBeforeRun=True       #flag to update pulse sequence before running
    self.TNMRRunTime=0              #time that current pulse sequence has been running
    
    #File address for Basic sequence templates
    self.templateDirectory='C:\TNMR\data\StandardPulseSequences'

    #Menu Actions
    #File
    self.ui.actionOpen_tnt_file.triggered.connect(self.openTNMRfile)
    self.ui.actionSave_Current_Pulse_Sequence.triggered.connect(self.saveTNMRfileAs)
    self.ui.actionUpdate_Pulse_Sequence.triggered.connect(self.updatePS)
    self.ui.actionSaveShimFile.triggered.connect(self.saveCurrentShimFile)
    self.ui.pbOpenFile.clicked.connect(self.openTNMRfile)
    #Shims
    self.ui.actionZeroShims.triggered.connect(self.zeroShims)
    self.ui.actionSetShimParameters.triggered.connect(self.setShimParameters)
    #Imaging
    self.ui.actionDisplayImage.triggered.connect(self.displayImage)  
    self.ui.actionPS_Open.triggered.connect(self.openPicoscope) 
    self.ui.actionPS_Close.triggered.connect(self.closePicoscope)
    #self.closeEvent.triggered.connect(self.closeMRIControl)           
    
    self.ui.cbPSTableList.activated.connect(self.showCurrentPSTable)
    self.ui.cbDerivedArrays.activated.connect(self.showDerivedArray)
    self.ui.sbPSDataPhase.valueChanged.connect(self.phaseIndexChange)
    self.ui.sbPSDataSlice.valueChanged.connect(self.sliceIndexChange)
    self.ui.sbPSDataParameter.valueChanged.connect(self.parameterIndexChange)
    self.ui.hsPSDataPhaseAdjust.valueChanged.connect(self.PSDataPhaseAdjust)
    self.ui.pbPSDataPlotF0PeakWidth.clicked.connect(self.plotF0PeakWidth)
    self.ui.pbAutoScalePlot.clicked.connect(self.autoRangePSdataPlot)
    self.ui.pbRunScout.clicked.connect(self.runScout)
    self.ui.pbFID.clicked.connect(self.runFID)
    self.ui.pbLoadShimFile.clicked.connect(self.loadShimFile)
    self.ui.pbRFTxCal.clicked.connect(self.runRFTxCal)
    self.ui.pbPlotRFcalSpectra.clicked.connect(self.plotRFTxCal)
    self.ui.pbRFCalAnalyze.clicked.connect(self.processRFTxCal)
    self.ui.sbRFCalSpectra.valueChanged.connect(self.plotRFTxCal)
    self.ui.rbRFCalPlotFID.toggled.connect(self.plotRFTxCal)
    self.ui.pbSetChillerSetPoint.clicked.connect(self.setPSsetpoint)
    self.ui.pbChillerOn.clicked.connect(self.turnOnPolySci)
    self.ui.pbChillerOff.clicked.connect(self.turnOffPolySci)
    #Eddy Current Correction ROutines
    self.ui.pbSaveECC.clicked.connect(self.saveCurrentECCFile)
    self.ui.pbLoadECC.clicked.connect(self.loadECCFile)
    self.ui.pbECCtoDefault.clicked.connect(self.setECCtoDefault)
    self.ui.pbScanECCParameter.clicked.connect(self.scanECCParameter)
    #self.ui.pbFastShim.clicked.connect(self.quickShim)
    self.ui.pbAutoShim.clicked.connect(self.autoShim)
    self.ui.pbUpdatePS.clicked.connect(self.updatePS)    
    self.ui.pbPSUpdateRun.clicked.connect(self.PSUpdateRun)
    self.ui.pbAddPStoQueue.clicked.connect(self.addPStoQueue)
    self.ui.pbAddCommandToRecipe.clicked.connect(self.addCommandToRecipe)
    self.ui.pbExectuteQueue.clicked.connect(self.executeRecipe)
    self.ui.pbClearMessages.clicked.connect(self.clearMessages)
    self.ui.pbSaveMessages.clicked.connect(self.saveMessages)
    self.ui.cbProtocol.activated.connect(self.openProtocol)       #opens a new protocol when a new protocol is selected 
    self.ui.cbGradOrientation.activated.connect(self.changeScanOrientation)     #Note activated ensures this event is only issued when the user changes the gradient orinetation, not the computer
    self.ui.dspboxFoVro.valueChanged.connect(self.plotSlicesInScout)
    self.ui.pbAbort.clicked.connect(self.TNMRAbort)
    self.ui.pbSaveRecipe.clicked.connect(self.saveRecipeFile)
    self.ui.pbOpenRecipe.clicked.connect(self.openRecipeFile)
    self.ui.pbClearRecipe.clicked.connect(self.clearRecipe)
    self.ui.pbAddFileToRecipe.clicked.connect(self.addFileToRecipe)
    self.ui.cbAddRecipeCommand.activated.connect(self.addRecipeCommand)
    self.ui.pbGenerateSlices.clicked.connect(self.generateSlices)
    self.ui.pbGenerateTIarray.clicked.connect(self.generateTIarray)
    self.ui.pbGenerateTEarray.clicked.connect(self.generateTEarray)
    self.ui.pbGenerateBvalues.clicked.connect(self.generateBvalues)
    self.ui.rbPSDataFID.toggled.connect(self.replotData)        #replot data in dockPSData after option buttons are pressed
    self.ui.rbPSDataFrequency.toggled.connect(self.replotData)
    self.ui.pbPSDataPhase.clicked.connect(self.setPSDataPhase)
    self.ui.rbPSDataMagnitude.toggled.connect(self.replotData)
    self.ui.rbPSDataPhase.toggled.connect(self.replotData)
    self.ui.rbPSDataReal.toggled.connect(self.replotData)
    self.ui.rbPSDataImag.toggled.connect(self.replotData)
    self.ui.chbSetObserveFreqToCenterFreq.stateChanged.connect(self.setObsFrequency)
    self.infx1.sigPositionChanged.connect(self.updatePSDataMarkers)
    self.infx2.sigPositionChanged.connect(self.updatePSDataMarkers)
    self.ui.spboxTNMRnAcqPoints.valueChanged.connect(self.TNMRnAcqPointsValueChanged)
    self.ui.spboxPhaseEncodes.valueChanged.connect(self.phaseEncodeValueChanged)
    self.ui.chbWideRefocus.stateChanged.connect(self.changeWideRefocus)
    #Scout and Slice Plan controls
    self.ui.hsSlicePlanMin.valueChanged.connect(self.changeSlicePlanMinMax)
    self.ui.hsSlicePlanMax.valueChanged.connect(self.changeSlicePlanMinMax)
    self.ui.chbShowGrid.stateChanged.connect(self.changeSlicePlanLayout)
    self.ui.cbSPColorMap.activated.connect(self.changeSlicePlanLayoutColormap)
    self.ui.chbShowSlices.stateChanged.connect(self.plotSlicesInScout)
    self.ui.pbSaveScoutSlicePlan.clicked.connect(self.saveScoutSlicePlan)
    self.ui.sbScoutSliceDisplay.valueChanged.connect(self.plotSlicesInScout)    #if slice display is changed replot sliceplan
    #Docked windows scaling                
    self.ui.dockPSData.visibilityChanged.connect(self.scaleDocks)       #scale docked widows when opened
    self.ui.dockPSData.setGeometry(800,950,800,20)
    self.ui.dockGradientCalibrations.visibilityChanged.connect(self.scaleDocks)
    self.ui.dockTables.visibilityChanged.connect(self.scaleDocks)
    self.ui.dockShims.visibilityChanged.connect(self.scaleDocks)
    self.ui.dockShims.setGeometry(1500,575,20,350)
    self.ui.dockRFCalibrations.visibilityChanged.connect(self.scaleDocks)
    self.ncurveMax=50   #maximum curves to plot, otherwise just plot individual curves so the program does not crash
    #***************Gradient Properties*****************************
    #self.GradientAmpMaxCurrent=319.58        #Not used in the program only self.Gxmax, self.Gymax, self.Gzmax
    self.GradientXAmpMaxCurrent=316.26
    self.GradientYAmpMaxCurrent=319.2
    self.GradientZAmpMaxCurrent=319.6
    self.desiredMaxGradient=0.100       #desired gradient when DAC output is 100
    self.GxCalMRI=1.030e-3  #1.000E-3         #T/m/A        #Not used in the program only self.Gxmax, self.Gymax, self.Gzmax
    self.GyCalMRI=1.025E-3     #1.01E-3     #T/m/A
    self.GzCalMRI=0.956E-3     #0.99E-3     #mT/m/A
    self.GxCal=self.GxCalMRI            #Not used in the program only self.Gxmax, self.Gymax, self.Gzmax
    self.GyCal=self.GyCalMRI
    self.GzCal=self.GzCalMRI
    self.gradCals={'X':self.GxCal,'Y':self.GyCal,'Z':self.GzCal}    #dictionary to relate image orientation to correct gradient eg 'XYZ' corresponds to RO gradient in X direction, phase gradient in Y direction, and slice in Z direction
    self.ui.leGxCal.setText('{:6.4f}'.format(self.GxCal*1000))  #display in mT/m/A
    self.ui.leGyCal.setText('{:6.4f}'.format(self.GyCal*1000))
    self.ui.leGzCal.setText('{:6.4f}'.format(self.GzCal*1000))
    self.A0xLowGDACMuliplier=100*self.desiredMaxGradient/( self.GradientXAmpMaxCurrent*self.GxCalMRI)      #NOminal value is         #Gradiant Dac multipliers set in Grad. Preemph.  Not used in the program only self.Gxmax, self.Gymax, self.Gzmax
    self.A0yLowGDACMuliplier=100*self.desiredMaxGradient/( self.GradientYAmpMaxCurrent*self.GyCalMRI) 
    self.A0zLowGDACMuliplier=100*self.desiredMaxGradient/( self.GradientZAmpMaxCurrent*self.GzCalMRI)
    self.message('Recommended A0.x={:6.3f} , A0.y={:6.3f}, A0.z={:6.3f} '.format(self.A0xLowGDACMuliplier,self.A0yLowGDACMuliplier,self.A0zLowGDACMuliplier), color='red') 
    self.AxmaxMRI=self.A0xLowGDACMuliplier*self.GradientXAmpMaxCurrent/100     #Maximum X gradient amp current when TNMR Amplitude is 100
    self.AymaxMRI=self.A0yLowGDACMuliplier*self.GradientYAmpMaxCurrent/100    #Maximum Y gradient amp current when TNMR Amplitude is 100
    self.AzmaxMRI=self.A0zLowGDACMuliplier*self.GradientZAmpMaxCurrent/100    #Maximum Z gradient amp current when TNMR Amplitude is 100
    self.Axmax=self.AxmaxMRI     #Maximum X gradient amp current when TNMR Amplitude is 100
    self.Aymax=self.AymaxMRI    #Maximum Y gradient amp current when TNMR Amplitude is 100
    self.Azmax=self.AzmaxMRI    #Maximum Z gradient amp current when TNMR Amplitude is 100
    self.ui.leAxmax.setText('{:6.3f}'.format(self.Axmax))
    self.ui.leAymax.setText('{:6.3f}'.format(self.Aymax))
    self.ui.leAzmax.setText('{:6.3f}'.format(self.Azmax))
    self.Gxmax=self.GxCal*self.Axmax
    self.Gymax=self.GyCal*self.Aymax
    self.Gzmax=self.GzCal*self.Azmax
    self.GrCal=self.GxCal   #gradient calibration in slice direction in T/m/A
    self.GpCal=self.GyCal
    self.GsCal=self.GzCal
    self.Armax=self.Axmax    #Maximum X gradient amp current when TNMR Amplitude is 100 dewtermined by A0 settings in the Grad PreEmph menu
    self.Apmax=self.Aymax    #Maximum Y gradient amp current when TNMR Amplitude is 100
    self.Asmax=self.Azmax    #Maximum Z gradient amp current when TNMR Amplitude is 100
    self.Gsmax=self.GsCal*self.Asmax        #maximum gradient in slice direction when pulse sequence value is 100
    self.Grmax=self.GrCal*self.Armax        #maximum gradient in slice direction
    self.Gpmax=self.GpCal*self.Apmax        #maximum gradient in slice direction
    self.message('Current Max Gradients(mT/m): GxMax= {:6.2f}, GyMax={:6.2f}x, GzMax={:6.2f}'.format(self.Gxmax*1000,self.Gymax*1000,self.Gzmax*1000), color='red')
    self.B0CompHzperDACC=-30      #calibration factor to convert frequency shift to B0 Comp values
    self.gradPreEmphHzperDACC=-3500      #calibration factor to convert frequency shift to gradient preemphasis values
    self.sliceDeltaF=6000        #slice frequency width for 1ms RF pulse in Hz
    self.xscale=1
    self.yscale=1
    self.HorizontalLabel=''
    self.VerticalLabel=''
    self.HorizontalUnits='voxel index'#
    self.RFCalPW=0.5E-3       #RF pulsewidth in s for RF power calibration, usually use 0.5 ms hard pulse
    self.RFAttn90Cal=16.7     #Nominal RF Attn for 90deg calibration pulse
    self.ui.leRFAttn90Cal.setText('{:6.3f}'.format(self.RFAttn90Cal))
    self.currentF0=0    #current center frequency of simple FID; used to set TNMR observe frequency
    
    #Setup Slice planning imageView windows
    #self.ui.chbShowSlices.setChecked(True)      #check show slice box to automatically show slice selectionn for those sequneces that uses slices
    self.sliceArrayCenter=0     #specifies the shift in mm of the slice array
    imvfont = QFont("Times", 6, QFont.Bold)
    self.imvAxial=pg.ImageView( view = pg.PlotItem())
    layout = QVBoxLayout()
    layout.setContentsMargins(0,0,0,0)
    layout.addWidget(self.imvAxial)
    self.ui.fraImvAxial.setLayout(layout)
    self.imvAxial.ui.histogram.setMaximumWidth(35)
    self.imvAxial.ui.histogram.setMinimumWidth(35)
    self.imvAxial.getHistogramWidget().gradientPosition='horizontal'
    #self.imvAxial.ui.histogram.setAxisItems(orientation='left', showValues=False)
    self.imvAxial.ui.histogram.hide()        #hide histograms and buttons in slice planing windows
    self.imvAxial.ui.roiBtn.hide()
    self.imvAxial.ui.menuBtn.hide()
    self.imvAxial.getView().getAxis('bottom').setPen('y')
    self.imvAxial.getView().getAxis('left').setPen('y')
    self.imvAxial.getView().getAxis('bottom').setTextPen('y')
    self.imvAxial.getView().getAxis('left').setTextPen('y') 
    self.imvAxial.getView().setLabel('bottom',"X(mm)")
    self.imvAxial.getView().setLabel('left',"Y(mm)")
    #self.imvAxial.getView().getAxis("left").setStyle(tickTextOffset=0)
   
    self.imvCoronal=pg.ImageView( view = pg.PlotItem())
    layout = QVBoxLayout()
    layout.setContentsMargins(0,0,0,0)
    layout.addWidget(self.imvCoronal)
    self.ui.fraImvCoronal.setLayout(layout)
    self.imvCoronal.ui.histogram.hide()
    self.imvCoronal.ui.histogram.setMaximumWidth(35)
    self.imvCoronal.ui.histogram.setMinimumWidth(35)
    self.imvCoronal.ui.roiBtn.hide()
    self.imvCoronal.ui.menuBtn.hide()
    self.imvCoronal.getView().getAxis('bottom').setPen('y')
    self.imvCoronal.getView().getAxis('left').setPen('y') 
    self.imvCoronal.getView().getAxis('bottom').setTextPen('y')
    self.imvCoronal.getView().getAxis('left').setTextPen('y') 
    self.imvCoronal.getView().setLabel('bottom',"Z(mm)")
    self.imvCoronal.getView().setLabel('left',"X(mm)")

    
    self.imvSagittal=pg.ImageView( view = pg.PlotItem())
    layout = QVBoxLayout()
    layout.setContentsMargins(0,0,0,0)
    layout.addWidget(self.imvSagittal)
    self.ui.fraImvSagittal.setLayout(layout)
    self.imvSagittal.ui.histogram.hide()
    self.imvSagittal.ui.histogram.setMaximumWidth(40)
    self.imvSagittal.ui.histogram.setMinimumWidth(40)
    self.imvSagittal.ui.roiBtn.hide()
    self.imvSagittal.ui.menuBtn.hide()
    self.imvSagittal.getView().getAxis('bottom').setPen('y')
    self.imvSagittal.getView().getAxis('left').setPen('y') 
    self.imvSagittal.getView().getAxis('bottom').setTextPen('y')
    self.imvSagittal.getView().getAxis('left').setTextPen('y') 
    self.imvSagittal.getView().setLabel('bottom',"Z(mm)")
    self.imvSagittal.getView().setLabel('left',"Y(mm)")
    
    self.pgXROIs=[]     #list of Coronal image slice ROIs
    self.pgYROIs=[]     #list of Sagittal image slice ROIs
    self.pgZROIs=[]     #list of Axial image slice ROIs
    
    self.sliceLayoutTypes=['Linear', 'Interpolated']
    self.TIarrayTypes=['Linear', 'PowerLaw']
    self.TEarrayTypes=['Linear', 'PowerLaw']
    self.TRarrayTypes=['Linear', 'PowerLaw']
    self.b_ValueArrayTypes=['Quadratic', 'Linear'] #, 'PowerLaw']
    
    self.rm= pyvisa.ResourceManager('C:/windows/system32/visa64.dll')       #Use NI pyvisa to control all USB and RS232 instruments
    self.ChillerOffsetTemperature=16
    self.ChillerOffsetSlope=0.125
    self.temperatureStableRange=4.0       #Maximum Temperature deviation from setpoint to temperature stable flag 
    self.temperatureStable=False
    self.temperatureSlope=0.001     #current temperature variation in degrees C per s
    self.alphaAv=0.1    #running average weighting factor
    self.Tsp=20     #Chiller tmeperature setpoint
    self.ChillerMaxT=60     #chiller maximum temperature setpoint
    self.ChillerMinT=-10    #chiller minimum temperature setpoint
    self.opsensTemperature=np.nan       #Fiber optic thermometer temperature, taken as sample temperature
    self.opsensTemperatureAv=np.nan 
    self.temperatureStableSlope=2E-4        # in K/s, limit below which the temrpature is considered stable, usually 0.2 mK per s
    self.TemperatureAverageFraction=0.01    #averages temperature change with ~1/self.TemperatureAverageFraction previous measurments to determin rate of change of temperature
    self.temperatureIntegralCoeff=0.001     #integral term for temperature control
    self.TcontrolErrorGain=2                #tmeprature error control gain, temperature setpoint= desiredTempperature-error*self.TcontrolErrorGain
     
    try:        #open fiberoptic thermometer control
      self.Opsensport='COM10'
      self.OpsensVisaAddress='ASRL10::INSTR'
      self.OpsensBaudRate=9600
      self.Opsens = self.rm.open_resource(self.OpsensVisaAddress, baud_rate=self.OpsensBaudRate)
      self.Opsens.read_termination = '\n' 
      self.Opsens.write_termination = '\r'
      self.OpsensIDN=self.Opsens.query('*IDN?')
      self.message("<b>Opsens connected: </b>" +self.OpsensIDN)
      #self.Opsens.write('(2):enab')
      self.Opsens.write('ch01:diag?')
      self.Opsens.read()
      self.message("Opsens diagnostic Ch01:{}, {}, {}, {}, {} ".format(self.Opsens.read(),self.Opsens.read(),self.Opsens.read(),self.Opsens.read(),self.Opsens.read()))
      self.Opsens.write('ch02:diag?')
      self.Opsens.read()
      self.message("Opsens diagnostic Ch02:{}, {}, {}, {}, {} ".format(self.Opsens.read(),self.Opsens.read(),self.Opsens.read(),self.Opsens.read(),self.Opsens.read()))
      self.opsensConnected=True
      self.opsensTemperature=float(self.readOpsensTemp())
      self.opsensTemperatureAv=self.opsensTemperature
      self.ui.cbMonitorTemperatures.setChecked(True)
    except:
      self.message('Cannot open Opsens')
      self.opsensConnected=False
 
      #raise
    self.PSport='COM9'
    self.PSBaudRate=38400
    self.PSsetpoint=np.nan
    self.PSTemperature=np.nan
    self.monitorPolyscience=False       #flag to determin if Polyscinece chiller is monitored
    try:
      self.PS = self.rm.open_resource(self.PSport, baud_rate=self.PSBaudRate)
      self.PS.read_termination = '\r' 
      self.PS.write_termination = '\r'
      self.PSfault=self.PS.query('RF')
      self.PSpumpspeed=self.PS.query('RM')
      self.PSoperating=self.PS.query('RO')
      self.message('PolyScience connected: operating={}, pumpspeed={}, fault={} '.format(self.PSoperating, self.PSpumpspeed,self.PSfault), bold=True)
      self.polycienceConnected=True
    except:
      self.message('Cannot open PolyScience')
      self.polycienceConnected=False
 
      #raise
    #monitor array
    self.nDataArrayPoints=6     #number of columns in the recipe data array
    self.dataArray=np.zeros((1,self.nDataArrayPoints))  #2d array containing [self.relTime, self.currentRecipeStep, self.Tsample, self.N2Flow, self.HeaterOutput])
    self.dataHeader='[self.relTime, self.currentRecipeStep, self.PSsetpoint, , self.PSTemperature, self.opsensTemperature, self.TNMRbusy])'   #Header for recipe data array that is used for plots and is saved
    self.dataPlot=plotWindow(self)
    self.dataPlot.dplot.setLabel('bottom', "Time (s)") #**self.labelStyle)
    self.dataPlot.dplot.setLabel('left', "Temperature(C)") #, **self.labelStyle) 
    self.arrayUpdateInterval=30 #update system data array every n updateIntervals
    self.nUpdates = 1 #number of system updates, used to determine when to save array data and output to logfile
    self.currentRecipeStep=0
    self.sampleTemperature=20       #current sample temperature as read by sample thermometer
    self.TemperatureNMRMin=0        #Minimum temperpature
    self.TemperatureNMRMax=80        #Minimum temperpature
    #Fitting parameters
    self.nfitpoints=100  #number of points used in fitting display
    #start timers and threads
    self.updateInterval =1.0   #update   interval for system monitor function in seconds
    #self.ui.dspboxUpdateInterval.setValue(self.updateInterval)
    # self.registry = ConnectRegistry(None,HKEY_CURRENT_USER)     #open windows registry
    # self.ScreenSaverTextKey = OpenKey(self.registry,r"SOFTWARE\Microsoft\Windows\CurrentVersion\Screensavers\ssText3d")
    # self.screenSaverText=QueryValueEx(self.ScreenSaverTextKey,'DisplayString') 
    # CloseKey(self.ScreenSaverTextKey)
    # print (self.screenSaverText)
    monitorTimer = QTimer(self)
    monitorTimer.timeout.connect(self.monitorInstruments)       #main routine to periodically monitor system
    monitorTimer.start(int(self.updateInterval*1000))
    self.startTime = time.time()        #start time for recipe
    self.picoscopeIsOpen=False #flag to indicate picoscope is open
    self.ui.txtRecipe.append('# <b>MRIControl Recipe: </b>' + time.strftime("%c"))
    self.ProtocolName='none'
    self.setupProtocol()
    
  def scaleDocks(self):
      '''scales docked windows when they are opened'''
      self.ui.dockPSData.resize(1200, 600)
      self.ui.dockGradientCalibrations.resize(1100, 400)
      self.ui.dockTables.resize(800, 700)
      self.ui.dockShims.resize(650, 300)
      self.ui.dockRFCalibrations.resize(1000, 400)
      
#*******System monitoring********************
  def monitorInstruments(self):
      '''Routines called on a timer to periodically monitor all instruments'''
      t = time.strftime("%c")
      self.relTime=time.time()-self.startTime        
      self.ui.leDateTime.setText(t)
#****Temperature Control******
      if self.opsensConnected and self.ui.cbMonitorTemperatures.isChecked():
            self.opsensTemperatureOld=self.opsensTemperature
            self.opsensTemperature=float(self.readOpsensTemp())
            self.ui.lblFOTemperature.setText(str(self.opsensTemperature))
            self.opsensTemperatureAv = self.rAv(self.opsensTemperatureAv,self.opsensTemperature,alpha=0.01)
      #Polyscience chiller
      if self.polycienceConnected and self.ui.cbMonitorTemperatures.isChecked() and self.monitorPolyscience:
          self.PSTemperature=float(self.readPSTemp())
          self.ui.lblPSTemp.setText('{:.3f}'.format(self.PSTemperature))
          #self.PSTempav = self.rAv(self.PSTempav,self.PSTemp,self.alphaAv)
          #self.ui.lePSTempav.setText('{:.3f}'.format(self.PSTempav))
          self.PSsetpoint=float(self.readPSsetpoint())
          self.ui.lePolySciSetpoint.setText('{:.3f}'.format(self.PSsetpoint))
          self.desiredTemperature=self.ui.dspboxDesiredSampleTemp.value()
      #Calculate rate of change of temperature
      if self.opsensConnected and self.ui.cbMonitorTemperatures.isChecked():
          self.temperatureSlope=(1-self.TemperatureAverageFraction)*self.temperatureSlope -self.TemperatureAverageFraction*(self.opsensTemperatureOld-self.opsensTemperature)/self.updateInterval
          self.ui.lblTslope.setText('{:.3f}'.format(1000*self.temperatureSlope))
          if np.absolute(self.temperatureSlope)<self.temperatureStableSlope:        #If temperature is not changing much make the indicator green
               self.ui.lblTslope.setStyleSheet("background-color: rgb(100, 255,100) ")
          else:     #If temperature is changing much make the indicator red
              self.ui.lblTslope.setStyleSheet("background-color: rgb(255, 100,100) ")
          if self.ui.rbControlTemperature.isChecked():
              if self.checkTemperatureStable():     #If temperature controlling and temperature is stable make indicator green
                   self.ui.lblFOTemperature.setStyleSheet("background-color: rgb(100, 255,100) ")
              else: #If temperature controlling and temperature is not stable make indicator red
                  self.ui.lblFOTemperature.setStyleSheet("background-color: rgb(255, 100,100) ")
          else:     #If not temperature controlling  make indicator gray
              self.ui.lblFOTemperature.setStyleSheet("background-color: rgb(250, 250,250) ")
      # if rbControlTemperature.isChecked():
      #     error=self.opsensTemperature-self.desiredTemperature
      #     self.temperatureIntegral+=-error*self.temperatureIntegralCoeff
      # else:
      #     self.temperatureIntegral=0  
#***TNMR Active Routines*****
      self.TNMRCheckAcquisition()
      if self.TNMRbusy: #When TNMR is busy set progress bar and get update info
        if self.picoscopeIsOpen:
            self.capturePicoscope()
        if self.shimmingInProgress:
            try:
                shimUnits=self.TNMR.currentFile.GetNMRParameter('Shim Units')
                if len(self.ShimUnits)<6:       #first 6 shim units are from previous data, so zero them
                    shimUnits=0
                self.ShimUnits.append(int(shimUnits))
                self.pltShimUnits.clear()
                self.pltShimUnits.plot(np.asarray(self.ShimUnits))
                self.getShimValues()
            except:
                pass
        self.ui.progressbarTNMR.setValue(int(100*self.TNMRRunTime/self.expectedRunTime))
        actualScans1D = int(self.TNMR.currentFile.GetNMRParameter("Actual Scans 1D"))
        actualPoints2D = int(self.TNMR.currentFile.GetNMRParameter("Actual Points 2D"))
        actualPoints3D = int(self.TNMR.currentFile.GetNMRParameter("Actual Points 3D"))
        actualPoints4D = int(self.TNMR.currentFile.GetNMRParameter("Actual Points 4D"))
        self.TNMR.finishTime=self.TNMR.currentFile.GetNMRParameter('Exp. Finish Time')
        self.ui.leFinishTime.setText('{}'.format(self.TNMR.finishTime))
        self.remainingTime=self.TNMR.currentFile.GetSequenceTime-self.TNMRRunTime
        self.ui.leTimeRemaining.setText(str(timedelta(seconds=round(self.remainingTime))))
        self.ui.leActual_npts.setText('{},{},{},{}'.format(actualScans1D,actualPoints2D,actualPoints3D,actualPoints4D))
      if self.TNMRjustFinished:
          self.ui.progressbarTNMR.setValue(100)
          self.ui.leFinishTime.setText('{}'.format(self.TNMR.finishTime))
          self.ui.leTimeRemaining.setText(str(timedelta(seconds=0)))
          self.TNMRjustFinished=False
#***Blink recipe running button if recipe is running****
      if self.recipeRunning:
        if self.nUpdates % 2 ==0:
            self.ui.lblRecipeRunning.setStyleSheet("background-color: rgb(0, 255, 0) ")
        else:
            self.ui.lblRecipeRunning.setStyleSheet("background-color: rgb(50, 200, 50)")
#****Log Monitor Data****
      newdata=np.array([self.relTime, self.currentRecipeStep, self.PSsetpoint,self.PSTemperature, self.opsensTemperature, self.TNMRbusy])
      if self.ui.chkShowDataArrayPlots.isChecked():
            self.dataPlot.show()
      else:
            self.dataPlot.hide()
      if self.nUpdates==1:  #on first update reset dataArray
          self.dataArray=np.zeros((1,self.nDataArrayPoints))
          self.dataArray[0,:]=newdata
      if (self.nUpdates % self.arrayUpdateInterval)==0:
        i=int(self.nUpdates/self.arrayUpdateInterval)
        self.dataArray=np.vstack((self.dataArray, newdata))
        self.dataPlot.plotData(self.dataArray)
        if self.ui.rbControlTemperature.isChecked():
            self.desiredChillerSetpoint=self.calculateDesiredChillerSetPoint()
            if np.absolute(self.PSsetpoint-self.desiredChillerSetpoint)>=0.1 and np.absolute(self.opsensTemperature-self.opsensTemperatureAv)<1:        #if the deisred setpoint deviates from the one that is set by more than 0.1C, change the setpoint, also make sure the current temp is close to the average temp
                self.setPSsetpoint(tsp=self.desiredChillerSetpoint)
                self.message('Changing Chiller Temperature Setpoint to {:.2f}C'.format(self.desiredChillerSetpoint))
      self.nUpdates+=1      #number of updates, reset when recipes start
#****************Code to control TNMR console**********************************    

  def openTNMR(self):
      self.TNMR.openConsole()
      self.message('TNMR console opened:', bold=True, ctime=True, color='green')

  def openProtocol(self):
      '''action when user changes comboBox protocol: opens standard pulse sequence in the self.templateDirectory directory'''
      self.ProtocolName=self.ui.cbProtocol.currentText()
      if self.ProtocolName != 'none':
            pfile=self.templateDirectory + '\\' + self.ProtocolName + '.tnt'
            self.openTNMRfile(file=pfile)
      else:
          self.setupProtocol()      #sets up the 'none' protocol
                
  def openTNMRfile(self, file=''):
    '''Main routine to open and upack a .tnt file into TNMR and upack pulse sequence paarmeters, will close existing active file is self.closeActiveFile flag is set'''
    self.message(str(file))
    '''Load .tnt file into TNMR and unpack pulse sequence parameters'''
    if self.closeActiveFile:        #if closeTNMRFile flag is set close current TNMR file before opening another one, prevents accumulation of a large number of files
        self.TNMR.closeActiveFile()
    if file=='' or file==False:
        f, ft = QFileDialog.getOpenFileName(self,'Open NMR file', self.studyDirectory, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
        if f=='':
            return
        else:
            self.NMRfileName=f     #self.NMRfileName is complete filename with full path
            DisplayImages=True  #display images if opening an existing image file
    else:
         self.NMRfileName=file
         DisplayImages=False     #do not display images if opening protocol template file
    self.studyDirectory=os.path.dirname(self.NMRfileName)
    self.message('Current study directory:' + self.studyDirectory)
    try:
        self.TNMR.openFile(self.NMRfileName)
    except:
        self.message('MRIcontrol:Cannot open TNMR file', color='red')
        return
    self.ui.leFileName.setText(self.NMRfileName)
    self.message('<b>Opened file: </b> '+self.NMRfileName)
    self.ProtocolName="none"
    for prot in self.protocolList:
        if self.NMRfileName.find(prot)!= -1:
            self.ProtocolName=prot     
    self.ui.cbProtocol.setCurrentText(self.ProtocolName)       
          #self.message('Opened TNMR file' +self.NMRfileName)
    self.ui.leTMRFobserve.setText('{:.6f}'.format(self.TNMR.ObsFreq/10**6)) #display in MHz
    self.ui.dspboxDwellTime.setValue(self.TNMR.DwellTime*1000)  #dwell time is the time between ADC reads, stored in s, but display in ms
    self.ui.dspboxLastDelay.setValue(self.TNMR.LastDelay)
    self.ui.leTNMRAcqTime.setText('{:.6f}'.format(self.TNMR.AcqTime))
    self.ui.leTNMRSW.setText('{:6.2f}'.format(self.TNMR.SW))
    self.nAcqPoints=self.TNMR.nAcqPoints
    if self.TNMR.SADimension==1:
        self.nAverages=self.TNMR.Scans1D    #na... are the actual number of points,slices, phase encodes, which may be different from the desired values
        self.nSlices=self.TNMR.Points2D
    else:
        self.nSlices=self.TNMR.Scans1D    #na... are the actual number of points,slices, phase encodes, which may be different from the desired values
        self.nAverages=self.TNMR.Points2D
    self.nPhases=self.TNMR.Points3D
    self.nParameters=self.TNMR.Points4D
    self.ui.spboxTNMRnAcqPoints.setValue(self.nAcqPoints)
    self.ui.spboxSlices.setValue(self.nSlices)
    self.ui.spboxAverages.setValue(self.nAverages)
    self.ui.spboxPhaseEncodes.setValue(self.nPhases)
    self.ui.spboxParameters.setValue(self.nParameters)
    self.ui.dspboxRFpw.setValue(self.TNMR.RFpw*1000)       #Display is in ms
    self.ui.dspboxRFpw180.setValue(self.TNMR.RFpw180*1000)       #Display is in ms
    self.ui.spboxReceiverGain.setValue(int(self.TNMR.ReceiverGain))
    self.ui.leGradientOrientation.setText('{}'.format(self.TNMR.GradientOrientation))
    self.ui.cbGradOrientation.setCurrentText(self.TNMR.getScanOrientation(self.TNMR.GradientOrientation))
    self.ui.leGradientOrientation.setText(self.scanOrientation[self.ui.cbGradOrientation.currentText()])
    self.ui.leExpectedAcqTime.setText(str(timedelta(seconds=round(self.TNMR.currentFile.GetSequenceTime))))
    self.expectedRunTime=self.TNMR.currentFile.GetSequenceTime
   
    self.ui.dspboxRFAttn90.setValue(self.TNMR.rfAttn90)
    self.ui.dspboxRFAttn180.setValue(self.TNMR.rfAttn180)

    self.currentFileComment=self.TNMR.currentFile.getComment
    self.ui.txtTNMRComment.setText('{}'.format(self.currentFileComment))
    self.TNMRTableList=self.TNMR.PSTableList.split(',')
    self.ui.cbPSTableList.clear()
    self.ui.cbPSTableList.addItems(self.TNMRTableList)
    self.showCurrentPSTable()
    self.dataArrayDimen=(self.TNMR.currentFile.GetNDSize(1),self.TNMR.currentFile.GetNDSize(2),self.TNMR.currentFile.GetNDSize(3),self.TNMR.currentFile.GetNDSize(4))
    self.tntData=self.getTNMRdata(self.dataArrayDimen)      #TNMR data usually has RO, slice, phase, parameter. 
    self.naPoints=self.dataArrayDimen[0]    #na... are the actual number of points,slices, phase encodes, which may be different from the desired values
    self.naSlice=self.dataArrayDimen[1]
    self.naPhase=self.dataArrayDimen[2]
    self.naParameter=self.dataArrayDimen[3]
    self.ui.sbPSDataSlice.setMaximum(self.naSlice-1)       #slider data selectors
    self.ui.sbPSDataPhase.setMaximum(self.naPhase-1)
    self.ui.sbPSDataParameter.setMaximum(self.naParameter-1)
    self.tfid=np.arange(self.naPoints) * self.TNMR.DwellTime     #time array for FID plots
    self.getShimValues()
    self.ui.leDataArrayDimen.setText(str(self.tntData.shape))
    self.ui.leiStart.setText('0')   #set initial data plot range to full FID/Spectra length
    self.ui.lejStop.setText(str(self.tntData.shape[0]))
    
    #read in gradient scaling values. all gradient values stored in T/m, while displayed in mT/m
    # self.GrCal=self.gradCals[self.TNMR.GradientOrientation[0]]
    # self.GpCal=self.gradCals[self.TNMR.GradientOrientation[1]]
    # self.GsCal=self.gradCals[self.TNMR.GradientOrientation[2]]
    # print('gradient RO,P,Sl Cals=',self.TNMR.GradientOrientation, self.GrCal,self.GpCal,self.GsCal)
       
    self.ui.leGspoilDAC.setText('{:6.6f}'.format(self.TNMR.GspoilDAC))
    self.Gspoil=self.TNMR.GspoilDAC/100*self.Gsmax
    self.ui.leGspoil.setText('{:6.3f}'.format(self.Gspoil*1000))
    
    self.ui.leGdpDAC.setText('{:6.6f}'.format(self.TNMR.GdpDAC))
    self.Gdp=self.TNMR.GdpDAC/100*self.Gsmax
    self.ui.leGdp.setText('{:6.6f}'.format(self.Gdp*1000))
    
    self.ui.leGpDAC.setText('{:6.6f}'.format(self.TNMR.GpDAC))
    self.Gp=self.TNMR.GpDAC/100*self.Gpmax
    self.ui.leGp.setText('{:6.6f}'.format(self.Gp*1000))
    
    self.ui.leGrDAC.setText('{:6.6f}'.format(self.TNMR.GrDAC))
    self.Gr=self.TNMR.GrDAC/100*self.Grmax
    self.ui.leGr.setText('{:6.6f}'.format(self.Gr*1000))
    
    self.ui.leGrrDAC.setText('{:6.6f}'.format(self.TNMR.GrrDAC))
    self.Grr=self.TNMR.GrrDAC/100*self.Grmax
    self.ui.leGrr.setText('{:6.6f}'.format(self.Grr*1000))
    
    self.ui.leGsDAC.setText('{:6.6f}'.format(self.TNMR.GsDAC))
    self.Gs=self.TNMR.GsDAC/100*self.Gsmax
    self.ui.leGs.setText('{:6.6f}'.format(self.Gs*1000))  
    
    self.ui.leGsrDAC.setText('{:6.6f}'.format(self.TNMR.GsrDAC))
    self.Gsr=self.TNMR.GsrDAC/100*self.Gsmax
    self.ui.leGsr.setText('{:6.6f}'.format(self.Gsr*1000))
    
    self.ui.letcrush.setText('{:6.6f}'.format(self.TNMR.tcrush))
    self.ui.lePhaseEncodePW.setText('{:6.6f}'.format(self.TNMR.tpe*1000))
    self.ui.letramp.setText('{:6.6f}'.format(self.TNMR.tramp))
 #update gradient pre-emphasis table, higlight used parameters in green
    for key in self.B0CompLabels:
        self.B0CompLabels[key].setText('{:6.4f}'.format(self.TNMR.B0CompValues[key]))
        self.B0CompLabels[key].setStyleSheet("background-color: rgb(200, 200, 200)")       #set background to gray
        if self.TNMR.B0CompValues[key]!=self.TNMR.B0CompValuesDefault[key]:   
            self.B0CompLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if values do not eaqual their default values
    for key in self.gradPreEmphasisLabels:
        self.gradPreEmphasisLabels[key].setText('{:6.4f}'.format(self.TNMR.gradPreEmphasisValues[key]))
        self.gradPreEmphasisLabels[key].setStyleSheet("background-color: rgb(200, 200, 200)")       #set background to gray 
        if self.TNMR.gradPreEmphasisValues[key]!=self.TNMR.gradPreEmphasisValuesDefault[key]: 
            self.gradPreEmphasisLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if values do not eaqual their default values
    self.FoVro=2*self.TNMR.SW/(self.Gammaf*np.absolute(self.Gr))        # Setting Field of View
    self.ui.dspboxFoVro.setValue(self.FoVro*1000)
    self.voxelSizeRO=self.FoVro/self.TNMR.nAcqPoints
    self.ui.leXVoxSize.setText('{:4.2f}'.format(self.voxelSizeRO*1000))     #voxel sizes in m, display in mm
    self.PErange=self.Gammaf*self.Gp*(self.TNMR.tpe+self.TNMR.tramp)*self.FoVro/self.TNMR.nAcqPoints
    self.ui.lePhaseEncodeRange.setText('{:4.2f}'.format(self.PErange))
    
    self.setupProtocol()
    self.calculateDerivedPSparameters() 
    self.plotData(self.tntData)
    if self.ProtocolName=="SCOUT":
        if DisplayImages:
            self.processScout(nRF=-1)
    else:
        if (DisplayImages and self.setupdict['DisplayImages']):
            self.displayImage()
    if self.ui.chbShowSlices.isChecked():   #plot new slice plan if checked
        self.ui.chbShowSlices.setChecked(False)    #Erases old slice plan
        self.ui.chbShowSlices.setChecked(True)     #plots new slice plan

  def getTNMRdata (self, arraydim):
    '''Extract raw data from current TNMR file'''
    rawData=self.TNMR.currentFile.getData
    datar=np.array(rawData)[0::2]       #data are real/ imaginary pairs
    datai=np.array(rawData)[1::2]
    self.data1d=np.empty(len(datar), np.cdouble)
    self.data1d.real=datar 
    self.data1d.imag=datai
    data=np.reshape(self.data1d, arraydim, order='F')        #reshape the 1d array into the 4d TNMR matrix, usually RO, slice, phase, parameter 
    return data

  def calculateDerivedPSparameters(self):
    '''calculates derived parameters and tables (slice thickness, slice position, TE, TI, TR) from pulse sequence tables'''
 
    self.ui.lete0.setText('{:4.2f}'.format(self.TNMR.te0*1000))      #helper parameter giving TE when no additional delays are present
    self.ui.leti0.setText('{:4.2f}'.format(self.TNMR.ti0*1000))      #helper parameter giving TI when no additional delays are present
    self.ui.letr0.setText('{:4.2f}'.format(self.TNMR.tr0*1000))      #helper parameter giving TR when no additional delays are present
            
    try:    #Construct RF excitation waveform if found and FT to calculate slice thickness
        if self.TNMR.PSTableList.find('rfShape')!=-1:
            wf=np.fromstring(self.TNMR.currentFile.GetTable('rfShape'), sep=' ')
            self.RFphase=np.fromstring(self.TNMR.currentFile.GetTable('rfPhase'), sep=' ')
            self.rfWaveform=wf*np.cos(self.RFphase*np.pi/2)
            self.RFWaveformIntegratedWeight=np.trapz(self.rfWaveform)/self.rfWaveform.shape[0]  #integrated waveform/npoints which has a maximal value of 100
            self.ui.lblRFWaveFormWeight.setText('{:6.2f}'.format(self.RFWaveformIntegratedWeight))        
            self.rfWaveformFT=np.fft.fftshift(np.fft.fft(self.rfWaveform))
            self.sliceDeltaF=self.findF0PeakWidth(np.absolute(self.rfWaveformFT))[1]/self.TNMR.RFpw
            self.ui.lblRFWaveFormFWHM.setText( '{:6.1f}'.format(self.sliceDeltaF))
            self.RFpowerScaling=100*self.RFCalPW/self.TNMR.RFpw/self.RFWaveformIntegratedWeight #REquired RF field for current RF pulse relative to standard 0.5 ms hard pulse
            self.RF90attnCor=20*np.log10(self.RFpowerScaling)
            self.ui.dsbRFPowerCor.setValue(self.RF90attnCor)
            self.RF90AttnSuggested=float(self.ui.leRFAttn90Cal.text())- self.RF90attnCor
            self.RF90attnSuggestedRounded=int(self.RF90AttnSuggested/0.5)*0.5
            self.RFPowerDerating=10**((self.RF90attnSuggestedRounded-self.RF90AttnSuggested)/20)
            self.ui.dsbRecommendedRF90Attn.setValue(self.RF90attnSuggestedRounded)
            self.ui.dsbRFscale.setValue(self.RFPowerDerating)
            self.ui.dsbPSRFAttn.setValue(self.RF90AttnSuggested)
            self.tipAngle=0.5*np.pi*10**(-(self.TNMR.rfAttn90-self.RF90AttnSuggested)/20)
            self.ui.dspTipAngle.setValue(self.tipAngle*180/np.pi)
    except:
        raise
    self.sliceThickness=self.sliceDeltaF/(self.Gammaf*self.Gs)
    self.ui.dspboxSliceThickness.setValue(self.sliceThickness*1000)
    try:
        if self.setupdict['SlicePositions']:     #if the pulsesequence protocol has slice positions, retrieve and set slice position parameters
            self.sliceFrequencies=np.fromstring(self.TNMR.currentFile.GetTable('sliceFrequencies'), sep=' ')
            self.slicePositions=-self.sliceFrequencies/(self.Gammaf*self.Gs)
            self.slicePositionList=np.array2string(self.slicePositions*1000, precision=2, separator=',').replace('[','').replace(']', '').split(',') #make a slice position list from slice position array
            self.ui.cbSlicePositions.clear()
            self.ui.cbSlicePositions.addItems(self.slicePositionList)
            if self.slicePositions.shape[0]>1:  #if there is more than one slice, calculate slice spacings
               self.sliceSpacing=np.min(np.absolute(self.slicePositions-self.slicePositions[0])[1:])
            else:
               self.sliceSpacing=0.0 
            self.ui.dspboxSliceSpacing.setValue(self.sliceSpacing*1000) #slice spacing in m, but displayed in mm
            #self.ui.leSlicePositions.setText(np.array2string(self.slicePositions*1000, precision=2))
            #self.message('Slice frequencies found, sliceFrequencies(Hz)={}, Slice positions(mm)={}'.format(np.array2string(self.sliceFrequencies,max_line_width=None, precision=2),np.array2string(self.slicePositions*1000,max_line_width=None, precision=2)))
    except:
        raise
    try:
         if self.setupdict['TE']:
            self.TEarray=2*np.fromstring(self.TNMR.currentFile.GetTable('teDelay').replace('m',''), sep=' ')*1E-3+self.TNMR.te0     #Echo times in s
            self.TEList=np.array2string(self.TEarray*1000, max_line_width=20000, separator=',', formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',') #make a  list from TE array
            self.ui.cbTE.clear()
            self.ui.cbTE.addItems(self.TEList)
            #self.ui.spboxParameters.setValue(len(self.TEarray))    #note may not want to do all values in TE array, use Points 4D
        #self.ui.leTE.setText(np.array2string(self.TEarray*1000, formatter={'float_kind':lambda x: "%.1f" % x}))

        #self.message('Slice frequencies found, sliceFrequencies(Hz)={}, Slice positions(mm)={}'.format(np.array2string(self.sliceFrequencies,max_line_width=None, precision=2),np.array2string(self.slicePositions*1000,max_line_width=None, precision=2)))
    except:
        print('MRIcontrol, calculateDerivedPSparameters: Cannot find teDelay array')
    try:
        if self.setupdict['TI']:
            if self.ProtocolName=='SEMS_IR' or self.ProtocolName=='GEMS_IR':
                self.TIarray=np.fromstring(self.TNMR.currentFile.GetTable('tiDelay').replace('m',''), sep=' ')*1E-3+self.TNMR.ti0     #Inversion times in s, display in ms
                self.TIarrayList=np.array2string(self.TIarray*1000, max_line_width=20000, separator=',', formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',') 
                self.ui.cbTI.clear()
                self.ui.cbTI.addItems(self.TIarrayList)
                self.ui.spboxParameters.setValue(len(self.TIarray))
            if self.ProtocolName=='T1IR_NMR':
                self.TIarray=np.fromstring(self.TNMR.currentFile.GetTable('ti_times').replace('m',''), sep=' ')*1E-3    #Inversion times in s, display in ms
                self.TIList=np.array2string(self.TIarray*1000, separator=',', formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',') #make a  list from self.TIarray
                self.ui.cbTI.clear()
                self.ui.cbTI.addItems(self.TIList)
                self.ui.spboxParameters.setValue(len(self.TIarray))
                #self.ui.leTI.setText(np.array2string(self.TIarray*1000, formatter={'float_kind':lambda x: "%.1f" % x}))
    except:
        raise
        print('MRIcontrol, calculateDerivedPSparameters: Cannot extract TI')
    try:
        if self.setupdict['TR']:
            pass
        else:
            self.TR=self.nSlices*(self.TNMR.LastDelay+self.TNMR.te0)
            self.ui.cbTR.clear()
            self.ui.cbTR.addItems(('{:6.2f}'.format(self.TR*1000),''))
    except:
        raise
    

    try:        #list diffusion gradients and b-values
        if self.setupdict['Bvalue']:
            self.diffdelta = self.TNMR.getTNMRfloat("delta")
            self.diffDelay = self.TNMR.getTNMRfloat("DiffDelay")
            self.tcrush = self.TNMR.getTNMRfloat("tcrush")
            self.tramp = self.TNMR.getTNMRfloat("tramp")
            self.message('diffdelta(ms)={:4.2f} , diffDelay(ms)={:4.2f} , tcrush(ms)={:4.2f} , tramp(ms)={:4.2f} '.format(1000*self.diffdelta,1000*self.diffDelay,1000*self.tcrush,1000*self.tramp))
            self.difGradArray=np.fromstring(self.TNMR.currentFile.GetTable("GrDiffArray"), sep=' ')*1E-3     #Read in grdient pulse amplitudes
            self.difGradArrayList=np.array2string(self.difGradArray*1000,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',')
            self.ui.cbDiffGradients.clear()
            self.ui.cbDiffGradients.addItems(self.difGradArrayList)
            self.bValueArray=self.STbvalue( g=self.difGradArray, delta=self.diffdelta, Delta=2*(self.diffDelay+self.tcrush+4*self.tramp)+self.diffdelta, risetime=self.tramp, pulsetype='trap')
            self.bValueArrayList=np.array2string(self.bValueArray,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.1f" % x}).replace('[','').replace(']', '').split(',')
            self.ui.cbBvalues.clear()
            self.ui.cbBvalues.addItems(self.bValueArrayList) 
    except:
        self.message('calculateDerivedPSparameters: Error setting up diffusion seqence', color='red')        

    try:
        if self.ProtocolName=='FID90ECC':
            self.gradRingdownDelay=np.fromstring(self.TNMR.currentFile.GetTable('gradRingdownDelay').replace('u','E-6').replace('m','E-3').replace('s',''), sep=' ')    #*1E-3+self.TNMR.ti0     
    except:
        raise
        print('MRIcontrol, calculateDerivedPSparameters: Cannot extract gradRingdownDelay')             
                  
  def setupProtocol(self):
    '''Enables/disables parameters for different protocols, sets signs of gradients'''
    self.message('Setting up Protocol: '+'self.'+self.ProtocolName + 'setup')
    self.setupdict=eval('self.'+self.ProtocolName + 'setup')     #picks the correct dictionary for the current protocol
    self.ui.lblProtocolDescription.setText(self.setupdict['ProtocolDescription'])
    self.ui.leTMRFobserve.setEnabled(self.setupdict['TMRFobserve'])
    self.ui.dspboxDwellTime.setEnabled(self.setupdict['DwellTime']) 
    self.ui.dspboxLastDelay.setEnabled(self.setupdict['LastDelay'])
    self.ui.leTNMRAcqTime.setEnabled(self.setupdict['TNMRAcqTime'])
    self.ui.leTNMRSW.setEnabled(self.setupdict['TNMRSW'])
    self.ui.spboxTNMRnAcqPoints.setEnabled(self.setupdict['TNMRnAcqPoints'])
    self.ui.spboxSlices.setEnabled(self.setupdict['Slices'])
    self.ui.spboxAverages.setEnabled(self.setupdict['Averages'])
    self.ui.spboxPhaseEncodes.setEnabled(self.setupdict['PhaseEncodes'])
    self.ui.spboxParameters.setEnabled(self.setupdict['Parameters'])
    self.ui.dspboxRFpw.setEnabled(self.setupdict['RFpw'])
    self.ui.spboxReceiverGain.setEnabled(self.setupdict['ReceiverGain'])
    self.ui.leGradientOrientation.setEnabled(self.setupdict['GradientOrientation'])
    self.ui.dspboxSliceThickness.setEnabled(self.setupdict['SliceThickness'])
    self.ui.dspboxSliceSpacing.setEnabled(self.setupdict['SliceSpacing'])
    self.ui.cbSlicePositions.setEnabled(self.setupdict['SlicePositions'])
    self.ui.pbGenerateSlices.setEnabled(self.setupdict['SlicePositions'])
    self.ui.dspboxFoVro.setEnabled(self.setupdict['FoVro'])
    self.ui.cbGradOrientation.setEnabled(self.setupdict['GradOrientation'])
    self.ui.dspboxRFAttn90.setEnabled(self.setupdict['RFAttn90'])
    self.ui.dspboxRFAttn180.setEnabled(self.setupdict['RFAttn180'])
    self.ui.leXVoxSize.setEnabled(self.setupdict['XVoxSize']) 
    self.ui.cbTE.setEnabled(self.setupdict['TE'])
    self.ui.pbGenerateTEarray.setEnabled(self.setupdict['TE'])
    self.ui.cbTR.setEnabled(self.setupdict['TR'])
    self.ui.pbGenerateTRarray.setEnabled(self.setupdict['TR'])
    self.ui.cbTI.setEnabled(self.setupdict['TI'])
    self.ui.pbGenerateTIarray.setEnabled(self.setupdict['TI'])  
    self.ui.dspTipAngle.setEnabled(self.setupdict['TipAngle'])
    self.ui.cbBvalues.setEnabled(self.setupdict['Bvalue'])
    self.ui.pbGenerateBvalues.setEnabled(self.setupdict['Bvalue'])
    self.ui.cbDiffGradients.setEnabled(self.setupdict['Bvalue'])
    self.GspoilSign=self.setupdict['GspoilSign']
    self.GdpSign=self.setupdict['GdpSign']
    self.GpSign=self.setupdict['GpSign']
    self.GrSign=self.setupdict['GrSign']
    self.GrrSign=self.setupdict['GrrSign']
    self.GsSign=self.setupdict['GsSign']
    self.GsrSign=self.setupdict['GsrSign']
    self.ui.tabOptions.setCurrentWidget(self.setupdict['OptionsTab'])
    #highlight enabled array by changing background color to red
    if self.setupdict['4DParam']=='none':
        self.ui.spboxParameters.setStyleSheet(self.defaulLabelColor)
    else:
        self.ui.spboxParameters.setStyleSheet(self.paramColor)
    if self.setupdict['4DParam']=='TE': 
        self.ui.cbTE.setStyleSheet(self.paramColor) 
    else:
        self.ui.cbTE.setStyleSheet(self.defaulLabelColor)         
    if self.setupdict['4DParam']=='TI': 
        self.ui.cbTI.setStyleSheet(self.paramColor) 
    else:
        self.ui.cbTI.setStyleSheet(self.defaulLabelColor)   
    if self.setupdict['4DParam']=='TR': 
        self.ui.cbTR.setStyleSheet(self.paramColor) 
    else:
        self.ui.cbTR.setStyleSheet(self.defaulLabelColor) 
    if self.setupdict['4DParam']=='bValue': 
        self.ui.cbDiffGradients.setStyleSheet(self.paramColor) 
        self.ui.cbBvalues.setStyleSheet(self.paramColor)
    else:
        self.ui.cbDiffGradients.setStyleSheet(self.defaulLabelColor) 
        self.ui.cbBvalues.setStyleSheet(self.defaulLabelColor)
    #Setup pulse sequence option tabs
    if self.ProtocolName=='GEMS':
        self.ui.dsbGEMSGspoil.setValue(self.TNMR.GspoilDAC) #display spoiler gradient magnitude (%)
        self.ui.dsbGEMStspoil.setValue(self.TNMR.tspoil*1000)   #display spoiler gradient duration in ms
    if self.ProtocolName=='SEMS' or self.ProtocolName=='SEMS_IR':
        self.ui.dsbSEMSGspoil.setValue(self.TNMR.GspoilDAC) #display spoiler gradient magnitude (%)
        self.ui.dsbSEMStspoil.setValue(self.TNMR.tspoil*1000)   #display spoiler gradient duration in ms   
        self.ui.dsbSEMSGcrush.setValue(self.TNMR.GdpDAC) #display spoiler gradient magnitude (%)
        self.ui.dsbSEMStcrush.setValue(self.TNMR.tcrush*1000)   #display spoiler gradient duration in ms         

                                            
  def updatePS(self):
    '''updates pulse sequence in current TNMR file'''
    self.Protocol=self.ui.cbProtocol.currentText()
    if self.ui.chbSetObserveFreqToCenterFreq.isChecked():       # sets observe frequency to current central peak position
        self.setObsFrequency()
    self.TNMR.ObsFreq= float(self.ui.leTMRFobserve.text())*10**6
    self.TNMR.DwellTime= self.ui.dspboxDwellTime.value()/1000.0     #dwell time is in s, displayed is in ms
    self.TNMR.SW=0.5/self.TNMR.DwellTime
    self.ui.leTNMRSW.setText('{:6.2f}'.format(self.TNMR.SW))    
    self.TNMR.LastDelay=self.ui.dspboxLastDelay.value()         #last delay value in s
    self.TNMR.nAcqPoints=self.ui.spboxTNMRnAcqPoints.value()
    if self.TNMR.SADimension==1:
        self.TNMR.Scans1D=self.ui.spboxAverages.value()    #na... are the actual number of points,slices, phase encodes, which may be different from the desired values
        self.TNMR.Points2D=self.ui.spboxSlices.value()
    if self.TNMR.SADimension==2:
        self.TNMR.Scans1D=self.ui.spboxSlices.value()    #na... are the actual number of points,slices, phase encodes, which may be different from the desired values
        self.TNMR.Points2D=self.ui.spboxAverages.value()
    if self.ui.spboxPhaseEncodes.isEnabled():
        self.TNMR.Points3D=self.ui.spboxPhaseEncodes.value()
    if self.ui.spboxParameters.isEnabled():
        self.TNMR.Points4D=self.ui.spboxParameters.value()
    self.nAcqPoints=self.ui.spboxTNMRnAcqPoints.value()
    self.nSlices= self.ui.spboxSlices.value()
    self.nAverages= self.ui.spboxAverages.value()
    self.nPhases=self.ui.spboxPhaseEncodes.value()
    self.regneratePhaseEncodeArray(self.nPhases,self.nAcqPoints )
    self.nParameters= self.ui.spboxParameters.value()
    if self.ui.dspboxRFpw.isEnabled():
        self.TNMR.RFpw=self.ui.dspboxRFpw.value()/1000       #Display is in ms
        self.TNMR.RFpw180=self.ui.dspboxRFpw180.value()/1000       #Display is in ms
    self.TNMR.ReceiverGain=self.ui.spboxReceiverGain.value()
    self.TNMR.GradientOrientation=self.ui.leGradientOrientation.text()
    self.TNMR.phaseEncodeArray=(np.array2string(self.phaseEncodeArray, separator=' ', formatter={'float_kind':lambda x: "%.3f" % x}).replace('[','').replace(']',''))
    self.writeTNMRComment()
 
    # #read in gradient scaling values   
    # self.ui.leGspoilDAC.setText('{:6.6f}'.format(self.TNMR.GspoilDAC))
    # self.Gspoil=self.TNMR.GspoilDAC/100*self.Gsmax
    # self.ui.leGspoil.setText('{:6.3f}'.format(self.Gspoil))
    #
    # self.ui.leGdpDAC.setText('{:6.6f}'.format(self.TNMR.GdpDAC))
    # self.Gdp=self.TNMR.GdpDAC/100*self.Gsmax
    # self.ui.leGdp.setText('{:6.6f}'.format(self.Gdp))
    #
    if self.ui.cbUseRFCalCorrection.isChecked() :
        self.ui.dspboxRFAttn90.setValue(self.RF90attnSuggestedRounded)
        self.ui.dspboxRFAttn180.setValue(self.RF90attnSuggestedRounded-6)
        self.ui.dsbRFPowerDerating.setValue(self.RFPowerDerating)
    self.TNMR.rfAttn90=self.ui.dspboxRFAttn90.value()
    self.TNMR.rfAttn180=self.ui.dspboxRFAttn180.value()
    self.ui.dspboxRFAttn180.setValue(self.TNMR.rfAttn180)
    self.FoVro=self.ui.dspboxFoVro.value()/1000
    #Set readout  gradient Gr, readout rewind gradient Grr, and Phase Encode gradient Gp values
    self.Gr=self.GrSign*2*self.TNMR.SW/ self.FoVro/self.Gammaf      # Setting readout gradient field of View
    self.TNMR.GrDAC=100*self.Gr/self.Grmax
    self.Grr=self.GrrSign*0.5*self.Gr*(self.TNMR.AcqTime+self.TNMR.tramp)/(self.TNMR.tpe+self.TNMR.tramp)
    self.TNMR.GrrDAC=100*self.Grr/self.Grmax
    self.ui.leGrDAC.setText('{:6.4f}'.format(self.TNMR.GrDAC))
    self.ui.leGr.setText('{:6.4f}'.format(self.Gr*1000))
    self.ui.leGrrDAC.setText('{:6.4f}'.format(self.TNMR.GrrDAC))
    self.ui.leGrr.setText('{:6.4f}'.format(self.Grr*1000))
    self.voxelSizeRO=self.FoVro/self.TNMR.nAcqPoints
    self.ui.leXVoxSize.setText('{:4.2f}'.format(self.voxelSizeRO*1000))     #voxel sizes in m, display in mm
    self.Gp=self.GpSign*0.5*self.TNMR.nAcqPoints/((self.TNMR.tpe+self.TNMR.tramp)*self.FoVro*self.Gammaf)
    self.TNMR.GpDAC=100*self.Gp/self.Gpmax
    self.ui.leGpDAC.setText('{:6.4f}'.format(self.TNMR.GpDAC))
    self.ui.leGp.setText('{:6.4f}'.format(self.Gp*1000))
    #Set slice  gradinet Gs and rewind gradient Gsr values if the sequence is 2D and uses slices
    if self.ui.dspboxSliceThickness.isEnabled() or self.ui.cbSlicePositions.isEnabled():
        self.sliceThickness=self.ui.dspboxSliceThickness.value()/1000
        self.Gs=self.GsSign*self.sliceDeltaF/(self.Gammaf*self.sliceThickness)
        self.TNMR.GsDAC=100*self.Gs/self.Gsmax
        if np.absolute(self.TNMR.GsDAC)>100:        #check to ensure gradient dac is not set above max/min values
            self.TNMR.GsDAC=100*np.sign(self.TNMR.GsDAC)
            self.Gs=self.Gsmax*self.TNMR.GsDAC/100
            self.sliceThickness==np.abs(self.sliceDeltaF/(self.Gammaf*self.Gs))
            self.ui.dspboxSliceThickness.setValue(self.sliceThickness*1000)
            self.message('Requested slice gradient above max value', color='red')
        self.ui.leGsDAC.setText('{:6.4f}'.format(self.TNMR.GsDAC))
        self.ui.leGs.setText('{:6.4f}'.format(self.Gs*1000))
        self.Gsr=self.GsrSign*0.6589*self.Gs
        self.TNMR.GsrDAC=100*self.Gsr/self.Gsmax
        self.ui.leGsrDAC.setText('{:6.4f}'.format(self.TNMR.GsrDAC))
        self.ui.leGsr.setText('{:6.4f}'.format(self.Gsr*1000))
    if self.ui.cbSlicePositions.isEnabled():
        try:        #update slice frequency array
             self.sliceFrequencyString=np.array2string(self.sliceFrequencies,  max_line_width=20000, precision=1, separator='  ').replace('[','').replace(']', '')
             self.TNMR.currentFile.SetTable('sliceFrequencies', self.sliceFrequencyString)
             #self.message('Slice frequencies found, sliceFrequencies(Hz)={}, Slice positions(mm)={}'.format(,np.array2string(self.slicePositions*1000,max_line_width=None, precision=2)))
        except:
             raise

    if self.ui.cbTI.isEnabled():
        try:        #update TI array
             if self.Protocol=='SEMS_IR':
                 self.tiArray=self.TIarray-self.TNMR.ti0
                 self.tiArray[self.tiArray <= 1e-6]=1e-6        #must be greater than 1 microsecond
                 self.tiArrayList=np.array2string(self.tiArray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3fm" % x}).replace('[','').replace(']', '')
                 self.TNMR.currentFile.SetTable('tiDelay', self.tiArrayList)
             if self.Protocol=='T1IR_NMR':
                 self.TIarray[self.TIarray <= 1e-6]=1e-6        #must be greater than 1 microsecond
                 self.tiArrayList=np.array2string(self.TIarray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3fm" % x}).replace('[','').replace(']', '')
                 self.TNMR.currentFile.SetTable('ti_times', self.tiArrayList)
        except:
             raise
    if self.ui.cbTE.isEnabled():
        try:        #update TE array for SEMS and GEMS protocols 
             if self.Protocol=='SEMS' or self.Protocol=='SEMS2':
                 self.teArray=self.TEarray/2-self.TNMR.te0/2
                 self.teArray[self.teArray <= 1e-6]=1e-6        #must be greater than 1 microsecond
                 self.teArrayList=np.array2string(self.teArray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3fm" % x}).replace('[','').replace(']', '')
                 self.TNMR.currentFile.SetTable('teDelay', self.teArrayList)
                 print('set teDealy: ' + self.teArrayList)
             if self.Protocol=='GEMS':
                 self.teArray=self.TEarray-self.TNMR.te0
                 self.teArray[self.teArray <= 1e-6]=1e-6        #must be greater than 1 microsecond
                 self.teArrayList=np.array2string(self.teArray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3fm" % x}).replace('[','').replace(']', '')
                 self.TNMR.currentFile.SetTable('teDelay', self.teArrayList)
             if self.Protocol=='T2SE_NMR':
                 self.TEarray[self.TEarray <= 1e-6]=1e-6        #must be greater than 1 microsecond
                 self.teArrayList=np.array2string(self.TEarray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3fm" % x}).replace('[','').replace(']', '')
                 self.TNMR.currentFile.SetTable('teDelay', self.teArrayList)
        except:
             raise
    if self.ui.cbTR.isEnabled():
        pass
    else:
        self.TR=self.nSlices*(self.TNMR.LastDelay+self.TNMR.te0)
        self.ui.cbTR.clear()
        self.ui.cbTR.addItems(('{:6.2f}'.format(self.TR*1000),''))
    if self.setupdict['Bvalue']:
        difGradString=np.array2string(self.difGradArray*1000,  max_line_width=20000, separator='  ',formatter={'float_kind':lambda x: "%.3f" % x}).replace('[','').replace(']', '')
        self.TNMR.currentFile.SetTable('GrDiffArray',difGradString)      
    self.TNMR.setPSparams()
    self.expectedRunTime=self.TNMR.currentFile.GetSequenceTime    
    self.ui.leExpectedAcqTime.setText(str(timedelta(seconds=round(self.expectedRunTime))))


  def changeWideRefocus(self):
    '''SEMS option to refocus wider than the excitation'''
    if self.ui.chbWideRefocus.isChecked():
        self.RF180AttnFactor=12
        self.RF180pwfactor=2
    else:
        self.RF180AttnFactor=6
        self.RF180pwfactor=1
    self.ui.dspboxRFAttn180.setValue(self.ui.dspboxRFAttn90.value()-self.RF180AttnFactor)
    self.ui.dspboxRFpw180.setValue(self.ui.dspboxRFpw.value()/self.RF180pwfactor)
      
      
      
  def generateSlices(self):
    '''Generates an array of slice frequencies from an input of desired slice positions)'''
    nslices, ok = QInputDialog().getInt(self, "Number of slices","# Slices", self.ui.spboxSlices.value(), 1, 500)
    if ok :
        self.ui.spboxSlices.setValue(nslices)
    else:
        return
    item, ok = QInputDialog().getItem(self, "Slice position protocol","Select slice layout type", self.sliceLayoutTypes, 0, False)
    if ok :
        if item=='Linear':
            pass
        else:
            return
    sliceThickness, ok = QInputDialog().getDouble(self, "Slice thickness","(mm)", self.ui.dspboxSliceThickness.value(), -100, 100,decimals=2)
    if ok :
        self.sliceThickness=sliceThickness/1000
        self.ui.dspboxSliceThickness.setValue(self.sliceThickness*1000)
    else:
        pass
    ss, ok = QInputDialog().getDouble(self, "Slice spacing","Slice spacing(mm)", self.ui.dspboxSliceSpacing.value(), 0, 50,decimals=2)
    if ok :
        self.sliceSpacing=ss/1000
        self.ui.dspboxSliceSpacing.setValue(self.sliceSpacing*1000)
    else:
        pass
    sliceCenter, ok = QInputDialog().getDouble(self, "Slice array center","Center slice position(mm)", self.sliceArrayCenter*1000, -100, 100)
    if ok :
        self.sliceArrayCenter=sliceCenter/1000
    else:
        pass
    self.Gs=self.GsSign*self.sliceDeltaF/(self.Gammaf*self.sliceThickness)
    self.TNMR.GsDAC=100*self.Gs/self.Gsmax
    if np.absolute(self.TNMR.GsDAC)>100:        #check to ensure gradient dac is not set above max/min values
            self.TNMR.GsDAC=100*np.sign(self.TNMR.GsDAC)
            self.Gs=self.Gsmax*self.TNMR.GsDAC/100
            self.sliceThickness=np.abs(self.sliceDeltaF/(self.Gammaf*self.Gs))
            self.ui.dspboxSliceThickness.setValue(self.sliceThickness*1000)
            self.message('Requested slice gradient={:6.2F} above max value'.format(self.TNMR.GsDAC), color='red')
    self.slicePositions=-1*(np.arange(nslices)-int(nslices/2))*(self.sliceSpacing)+self.sliceArrayCenter
    self.sliceFrequencies=-self.slicePositions*self.Gammaf*self.Gs      #set slice frequencies from slicePosition array
    self.slicePositionList=np.array2string(self.slicePositions*1000, precision=2, max_line_width=20000, separator=',').replace('[','').replace(']', '').split(',') #make a slice position list from slice position array
    self.ui.cbSlicePositions.clear()
    self.ui.cbSlicePositions.addItems(self.slicePositionList)
    self.ui.dspboxSliceSpacing.setValue(self.sliceSpacing*1000) #slice spacing in m, but displayed in mm
    self.plotSlicesInScout()        #update slice plan
    self.writeTNMRComment(write=False)      #update comment text
    
  def generateTIarray(self):
    '''Generates an array of inversion times TI)'''
    nTIs, ok = QInputDialog().getInt(self, "Number of TIs","# TIs", self.ui.spboxParameters.value(), 1, 50)
    if ok :
        self.ui.spboxParameters.setValue(nTIs)
    else:
        return
    tiprotocol, ok = QInputDialog().getItem(self, "TI protocol","Select TI array type", self.TIarrayTypes, 0, False)
    if ok :
        pass
    else:
        tiprotocol='Linear'
    initialTI, ok = QInputDialog().getDouble(self, "Initial TI","(ms)", self.TNMR.ti0*1000, self.TNMR.ti0*1000, 1000)
    if ok :
        self.initialTI=initialTI/1000
    else:
        self.initialTI=0.005
    finalTI, ok = QInputDialog().getDouble(self, "Final TI","Final TI(ms)", 1000, 0, 3000)
    if ok :
        self.finalTI=finalTI/1000
    else:
        self.finalTI=1
    if tiprotocol=='Linear':
        self.TIarray=np.linspace(initialTI, finalTI, num=nTIs)/1000
    if tiprotocol=='PowerLaw':
        power=np.exp(np.log(self.finalTI/self.initialTI)/(nTIs-1))      #calculate multipier from min, max, and number of TEs  
        self.TIarray=self.initialTI*power**np.arange(nTIs)    
    self.TIarrayList=np.array2string(self.TIarray*1000,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',')
    self.ui.cbTI.clear()
    self.ui.cbTI.addItems(self.TIarrayList)

  def generateTEarray(self):
    '''Generates an array of echo times TE, input number of echo times, type of array (linear, powerlaw), minimum and maximum values
    The input to the pulse sequence is an array teDelay values where TE=2TEx1+te0'''
    nTEs, ok = QInputDialog().getInt(self, "Number of Echo Times","# TEs", self.ui.spboxParameters.value(), 1, 50)
    if ok :
        self.ui.spboxParameters.setValue(nTEs)
    else:
        return
    teprotocol, ok = QInputDialog().getItem(self, "TE protocol","Select TE array type", self.TEarrayTypes, 0, False)
    if ok :
        pass
    else:
        teprotocol='Linear'
    if self.ProtocolName=='SEMS' or self.ProtocolName=='SEMS2':       #minimum SE time for MRI sequence is 12ms, NMR is 1us
        temin=12
    elif self.ProtocolName=='T2SE_NMR':
        temin=1
    else:
        temin=1 
    initialTE, ok = QInputDialog().getDouble(self, "Initial TE>12ms","(ms)", temin, temin, 1000,decimals=3)
    if ok :
        self.initialTE=initialTE/1000
    else:
        self.initialTE=0.005
    finalTE, ok = QInputDialog().getDouble(self, "Final TE","Final TE(ms)", 1000, 0, 3000, decimals=3)
    if ok :
        self.finalTE=finalTE/1000
    else:
        self.finalTE=1
    if teprotocol=='Linear':
        self.TEarray=np.linspace(initialTE, finalTE, num=nTEs)/1000
    if teprotocol=='PowerLaw':
        power=np.exp(np.log(self.finalTE/self.initialTE)/(nTEs-1))      #calculate multipier from min, max, and number of TEs
        self.TEarray=self.initialTE*(power**np.arange(nTEs))    
    self.TEarrayList=np.array2string(self.TEarray*1000,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',')
    self.ui.cbTE.clear()
    self.ui.cbTE.addItems(self.TEarrayList)

  def generateBvalues(self):
    '''Generates an array of diffusion gradinets and b-values, input number , type of array (linear, powerlaw), minimum and maximum values
    The input to the pulse sequence is an array teDelay values where TE=2TEx1+te0'''
    nBvs, ok = QInputDialog().getInt(self, "Number of gradient pulses, b-values","# b-values", self.ui.spboxParameters.value(), 1, 50)
    if ok :
        self.ui.spboxParameters.setValue(nBvs)
    else:
        return
    difprotocol, ok = QInputDialog().getItem(self, "Diffusion protocol","Select b-value array type", self.b_ValueArrayTypes, 0, False)
    if ok :
        pass
    else:
        difprotocol='Linear'
    self.initialDifGradient=0.0
    finalGrad, ok = QInputDialog().getDouble(self, "Final gradient amplitude","Final gradient(mT/m)", 100, 0, 100, decimals=3)
    if ok :
        self.finalGrad=finalGrad/1000
    else:
        self.finalGrad=0.1
    if difprotocol=='Linear':
        self.difGradArray=np.linspace(self.initialDifGradient, finalGrad, num=nBvs)/1000
    if difprotocol=='Quadratic':
        sqrtarray=np.sqrt(np.arange(nBvs)/(nBvs-1))
        self.difGradArray=self.finalGrad*sqrtarray   
    self.difGradArrayList=np.array2string(self.difGradArray*1000,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',')
    self.ui.cbDiffGradients.clear()
    self.ui.cbDiffGradients.addItems(self.difGradArrayList)
    self.bValueArray=self.STbvalue( g=self.difGradArray, delta=self.diffdelta, Delta=2*(self.diffDelay+self.tcrush+4*self.tramp)+self.diffdelta, risetime=self.tramp, pulsetype='trap')
    self.bValueArrayList=np.array2string(self.bValueArray,max_line_width=20000, separator=',',formatter={'float_kind':lambda x: "%.2f" % x}).replace('[','').replace(']', '').split(',')
    self.ui.cbBvalues.clear()
    self.ui.cbBvalues.addItems(self.bValueArrayList)
          
  def showCurrentPSTable(self):
      '''Display chosen pulse sequence table''' 
      currentTable=self.TNMR.currentFile.GetTable(self.ui.cbPSTableList.currentText())
      self.currentTableArray=np.fromstring(currentTable, dtype=float, sep=' ')
      self.ui.lblPSTableList.setText(currentTable)
      self.ui.leNTableElements.setText("{}".format(len(self.currentTableArray)))
      self.ui.pltTable.clear()
      #self.ui.pltTable.setTitle('Amplitude repeat=' )#+str(self.repeatIndex), **self.titleStyle) 
      self.ui.pltTable.plot(self.currentTableArray, pen='g', symbol='x', symbolPen='g', symbolBrush=0.2, name=currentTable)
      
  def showDerivedArray(self):
      '''Display chosen pulse sequence table'''
      self.ui.teDerivedArrays.setText('')
      self.ui.leNDerivedArrayElements.setText('')
      self.ui.pltDerivedArrays.clear() 
      currentArrayName=self.ui.cbDerivedArrays.currentText()
      try:
          if currentArrayName=='TE':
              currentDerivedArray=self.TEarray
          if currentArrayName=='TI':
              currentDerivedArray=self.TIarray
          if currentArrayName=='TR':
              currentDerivedArray=self.TRarray
          if currentArrayName=='SlicePosition':
              currentDerivedArray=self.slicePositions
          if currentArrayName=='RFWaveform':
              currentDerivedArray=self.rfWaveform         
          if currentArrayName=='RFWaveformFT':
              currentDerivedArray=np.absolute(self.rfWaveformFT)  
          self.ui.teDerivedArrays.setText(np.array2string(currentDerivedArray,max_line_width=160))
          self.ui.leNDerivedArrayElements.setText("{}".format(len(currentDerivedArray)))
          self.ui.pltDerivedArrays.clear()
          self.ui.pltDerivedArrays.setTitle(currentArrayName)
          self.ui.pltDerivedArrays.plot(currentDerivedArray, pen='g', symbol='x', symbolPen='g', symbolBrush=0.2, name=currentArrayName)  
      except:
          pass    

  def openStudyDirectory(self):
      self.studyDirectory = QFileDialog.getExistingDirectory(None,'Open study directory',self.studyDirectory,QFileDialog.ShowDirsOnly)
      self.ui.leStudyDirectory.setText(self.studyDirectory)
#***********Scout***************
  def runScout(self):
      '''runs a simple 3-orientation Scout sequence'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.ui.pbRunScout.setStyleSheet("background-color : lightgreen")
      app.processEvents()      
      self.ui.cbProtocol.setCurrentText('SCOUT')        #Sets protocol to scout and loads SCOUT template
      self.openProtocol()
      self.ui.spboxAverages.setValue(self.ui.sbScoutAverages.value())
      self.PSUpdateRun()
      self.ui.pbRunScout.setStyleSheet("background-color: rgb(240, 240, 240)")
      
  def processScout(self, nRF=0, raw=False): 
          '''Process scout which has 3 views concatinated, nRF is the RF channel number, -1 means only 1 channel present
          raw is a flag to plot raw (kspace) data otherwise reconstructed data will be displayed'''
          # if nRF !=-1:
          #   self.scoutData=self.tntData[nRF::4,:,:,0]     #extract channel 1 from  CH1,2,3,4 data for Magnetica data
          # else:
          self.scoutData=self.tntData[:,:,:,0] #scoutData is a 3d array with RO coronal+ sagittal+axial, slice, phase
          dshape=self.scoutData.shape
          columns=int(dshape[0]/3)  #Sagittal, coronal, axial need to be separated
          rows=dshape[2]         
          npad=int((columns-rows)/2) 
          self.xscale=1000*self.FoVro/columns
          self.yscale=self.xscale
          xmin=-1000*self.FoVro/2       #upper left value of image in mm
          ymin=-1000*self.FoVro/2
          axial=self.scoutData[2*columns:3*columns,:,:]   #Axial is the first third of readout
          axial=np.swapaxes(axial,0,1)  #move the slice index to the first dimension
          self.axialScout=np.pad(axial,((0,0),(0,0),(npad,npad)))   #pad so we have a square array
          #self.axialScoutMax=np.max(np.absolute(self.axialScout[0,:,:]))
          self.fftdataAxial=np.fft.fftshift(np.fft.fft2(self.axialScout))
          axmag=np.absolute(self.fftdataAxial)
          axmag=axmag/axmag.max()  #normalize
          if raw:
              self.imvAxial.setImage(np.absolute(self.axialScout[0,:,:]),scale = (self.xscale,self.yscale))
          else:
              self.imvAxial.setImage(np.fliplr(axmag[0,:,:]),pos = (xmin,ymin),scale = (self.xscale,self.yscale))
          self.imvAxial.setLevels(min=0.2,max=0.6)
          coronal=self.scoutData[0:columns,:,:]   #Axial is the first third of readout
          coronal=np.swapaxes(coronal,0,1)  #move the slice index to the first dimension
          self.coronalScout=np.pad(coronal,((0,0),(0,0),(npad,npad)))   #pad so we have a square array
          self.fftdataCoronal=np.fft.fftshift(np.fft.fft2(self.coronalScout))
          comag=np.absolute(self.fftdataCoronal)
          comag=comag/comag.max()  #normalize
          self.imvCoronal.setImage(np.flipud(comag[0,:,:]),pos = (xmin,ymin),scale = (self.xscale,self.yscale))
          
          sagittal=self.scoutData[columns:2*columns,:,:]   #sagittal is the first third of readout
          sagittal=np.swapaxes(sagittal,0,1)  #move the slice index to the first dimension
          self.sagittalScout=np.pad(sagittal,((0,0),(0,0),(npad,npad)))   #pad so we have a square array
          self.fftdataSagittal=np.fft.fftshift(np.fft.fft2(self.sagittalScout))
          samag=np.absolute(self.fftdataSagittal)
          samag/=samag.max()  #normalize
          self.imvSagittal.setImage(np.fliplr(np.transpose(samag[0,:,:])),pos = (xmin,ymin),scale = (self.xscale,self.yscale))
          self.ui.hsSlicePlanMin.setValue(0)
          self.ui.hsSlicePlanMax.setValue(100) 
          #self.message('<b>MRI Scout processing:</b> Separated Coronal,Saggital,Axial slices', ctime=True)      
  def changeSlicePlanMinMax(self):
    '''Changes windowing in the slice plan images'''
    minv=self.ui.hsSlicePlanMin.value()/100
    maxv=self.ui.hsSlicePlanMax.value()/100  
    self.imvAxial.setLevels(min=minv,max=maxv)
    self.imvCoronal.setLevels(min=minv,max=maxv)
    self.imvSagittal.setLevels(min=minv,max=maxv)
  def changeSlicePlanLayout(self):
      if self.ui.chbShowGrid.isChecked():
          self.imvAxial.getView().showGrid(True, True)
          self.imvCoronal.getView().showGrid(True, True)
          self.imvSagittal.getView().showGrid(True, True)
      else:
          self.imvAxial.getView().showGrid(False, False)
          self.imvCoronal.getView().showGrid(False, False)
          self.imvSagittal.getView().showGrid(False, False)          
             
  def changeSlicePlanLayoutColormap(self):
     cm=self.ui.cbSPColorMap.currentText()
     self.imvAxial.setPredefinedGradient(cm)
     self.imvCoronal.setPredefinedGradient(cm)
     self.imvSagittal.setPredefinedGradient(cm)
     
  def plotSlicesInScout(self):
      '''Plots/Erases slice projections in the Scout windows'''
      try:      #erase current slice plan
              for roi in self.AxialSliceProjections:
                  self.imvAxial.getView().removeItem(roi)
              for roi in self.CoronalSliceProjections:
                  self.imvCoronal.getView().removeItem(roi)
              for roi in self.SagittalSliceProjections:
                  self.imvSagittal.getView().removeItem(roi)
      except:   #note there may not be any slices to erase
            pass
      if self.setupdict['SlicePositions']==False:        #protocol does not have a slice plan
          return
      if self.ui.chbShowSlices.isChecked():     #plot slice plan
          nslices=self.ui.spboxSlices.value()
          self.ui.sbScoutSliceDisplay.setMaximum(nslices-1)
          FoV=self.ui.dspboxFoVro.value() # in mm, not meters
          sliceThickness=self.ui.dspboxSliceThickness.value()
          Xc=np.zeros(nslices) #slice centers
          Yc=np.zeros(nslices)
          Zc=np.zeros(nslices)
          self.AxialSliceProjections=[] #list of ROI slice projections
          self.CoronalSliceProjections=[] #list of ROI slice projections
          self.SagittalSliceProjections=[] #list of ROI slice projections
          gradOrient=self.ui.leGradientOrientation.text()
          
          if gradOrient=='XYZ' or gradOrient=='YXZ':
              dx=FoV
              dy=FoV
              dz=sliceThickness
              Zc=(self.slicePositions*1000-sliceThickness/2)+FoV/2
          if gradOrient=='XZY' or gradOrient=='ZXY':
              dx=FoV
              dz=FoV
              dy=sliceThickness
              Yc=(self.slicePositions*1000-sliceThickness/2)+FoV/2
          if gradOrient=='YZX' or gradOrient=='ZYX':
              dz=FoV
              dy=FoV
              dx=sliceThickness
              Xc=(self.slicePositions*1000-sliceThickness/2)+FoV/2
          for slice in range(nslices):
              if self.ui.sbScoutSliceDisplay.value()==-1 or self.ui.sbScoutSliceDisplay.value()==slice:
                  self.AxialSliceProjections.append(pg.RectROI([Xc[slice]-FoV/2, Yc[slice]-FoV/2], [dx, dy], pen=self.slicepen))
                  #roi.addRotateHandle([1, 0], [0.5, 0.5])
                  self.AxialSliceProjections[-1].removeHandle(0)
                  self.imvAxial.getView().addItem(self.AxialSliceProjections[-1])
                  self.CoronalSliceProjections.append(pg.RectROI([Zc[slice]-FoV/2, Xc[slice]-FoV/2], [dz, dx], pen=self.slicepen))
                  self.CoronalSliceProjections[-1].removeHandle(0)
                  self.imvCoronal.getView().addItem(self.CoronalSliceProjections[-1])
                  self.SagittalSliceProjections.append(pg.RectROI([Zc[slice]-FoV/2, Yc[slice]-FoV/2], [dz, dy], pen=self.slicepen))
                  self.SagittalSliceProjections[-1].removeHandle(0)
                  self.imvSagittal.getView().addItem(self.SagittalSliceProjections[-1])
      self.imvSagittal.show()
      self.imvCoronal.show()
      self.imvAxial.show()
      
  def saveScoutSlicePlan(self):
    '''Saves .png files of scout with slice plan'''
    f, ft = QFileDialog.getSaveFileName(self,'Save file', self.studyDirectory, "png (*.png)")        #Note self.FileName is a qString not a string
    if f=='':
        return
    else:
        exporter = pg.exporters.ImageExporter(self.imvAxial.getView())
        exporter.parameters()['width'] = 1000  
        exporter.export(f.replace('.png', '_axial.png'))     
        exporter = pg.exporters.ImageExporter(self.imvCoronal.getView())
        exporter.parameters()['width'] = 1000  
        exporter.export(f.replace('.png', '_coronal.png'))     #self.NMRfileName is complete filename with full path
        exporter = pg.exporters.ImageExporter(self.imvSagittal.getView())
        exporter.parameters()['width'] = 1000  
        exporter.export(f.replace('.png', '_sagittal.png'))     #self.NMRfileName is complete filename with full path
                       
#***********FID routines***********       
  def runFID(self):
      '''Runs simple FID pulse sequence, finds center frequency and line width'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.ui.pbFID.setStyleSheet("background-color : lightgreen")
      # app.processEvents()      
      # self.ui.cbProtocol.setCurrentText('ShimFIDHP')        #Sets protocol to scout and loads SCOUT template
      # self.PSUpdateRun()
      self.message('Run FID', bold=True,ctime=True)
      app.processEvents()
      self.ui.cbProtocol.setCurrentText('ShimFIDHP')
      self.openProtocol()
      if self.ui.chbSetObserveFreqToCenterFreq.isChecked():
          self.setObsFrequency()
          self.TNMR.currentFile.SetNMRParameter("Observe Freq.", '{:.6f}MHz'.format(self.TNMR.ObsFreq/10**6))
      self.runCurrentTNMRFile() 
      self.dataArrayDimen=(self.TNMR.currentFile.GetNDSize(1),self.TNMR.currentFile.GetNDSize(2),self.TNMR.currentFile.GetNDSize(3),self.TNMR.currentFile.GetNDSize(4))
      self.tntData=self.getTNMRdata(self.dataArrayDimen)
      if self.subtractFIDBackground:
        bstart=int(self.blRegionStart*self.tntData.real.shape[0])   #calculate baselines as the average of the data beyond self.blRegion
        bstop=int(self.blRegionStop*self.tntData.real.shape[0])   #calculate baselines as the average of the data beyond self.blRegion
        self.FIDBaseline=np.average(self.tntData[bstart:bstop,0,0,0].real)+1j*np.average(self.tntData[bstart:bstop,0,0,0].imag)    #array of complex baseline values
        self.tntData-=self.FIDBaseline     # baseline is the averagrion value of last part of the data
        self.message('Subtracting FID Background:'+ 'data shape {0},{1},{2},{3}, baseline={4.real:.2f} {4.imag:+.2f}i)'.format(*self.tntData.shape,self.FIDBaseline))

      self.ui.rbPSDataSpectra.setChecked(True) #set PSData plot to display spectra      
      self.plotData(self.tntData)
      self.ui.dockPSData.setFloating(True)
      self.setPSDataPhase()
      self.ui.leFIDFWHM.setText('{:6.2F}'.format(self.FirstPeakFWHM))
      self.ui.pbFID.setStyleSheet("background-color: rgb(240, 240, 240)")
      
#***********FID routines***********      
  def processFIDECC(self):
      '''Process FID with preRF gradient to determine B0 compensation and Eddy Current Corrections (ECC)
      Use 50 mm NiCL2 sphere with short T1, T2, Shim and get FID with centered frequecny, run ECCB0Comp, enter times constanc=ts and Amplitudes'''
      self.ui.rbPSDataSpectra.setChecked(True) #set PSData plot to display spectra      
      self.plotData(self.tntData)
      self.ui.dockPSData.setFloating(True)
      self.setPSDataPhase(phaseSpectra=-1)
      self.ui.leFIDFWHM.setText('{:6.2F}'.format(self.FirstPeakFWHM))
      self.plotF0PeakWidth()
      self.fitECCData(self.gradRingdownDelay, self.F0PeakWidth[:,0], logSpace=True, nTimeConstants=2, VaryBaseline=False)
      self.message("ECC F0:  t1(ms)={:.2f}, A(Hz)={:.2f}, DacCounts={:.2f};   t2(ms)={:.2f}, B(Hz)={:.2f}, DacCounts={:.2f}".format(1000*self.ECCt1t2ABC[0],
        self.ECCt1t2ABC[2],self.ECCt1t2ABC[2]/self.B0CompHzperDACC,1000*self.ECCt1t2ABC[1],self.ECCt1t2ABC[3],self.ECCt1t2ABC[3]/self.B0CompHzperDACC), color='orange', bold=True)
      self.dataMagPlot.plot(self.ECCfitx,self.ECCfity, name='F0fit',pen=self.open)   #plot Mag
      self.fitECCData(self.gradRingdownDelay, self.F0PeakWidth[:,1], logSpace=True, nTimeConstants=2, VaryBaseline=True)
      self.message("ECC FWHM:  t1(ms)={:.2f}, A(Hz)={:.2f}, DacCounts={:.2f};   t2(ms)={:.2f}, B(Hz)={:.2f}, DacCounts={:.2f}".format(1000*self.ECCt1t2ABC[0],
        self.ECCt1t2ABC[2], self.ECCt1t2ABC[2]/self.gradPreEmphHzperDACC,1000*self.ECCt1t2ABC[1],self.ECCt1t2ABC[3],self.ECCt1t2ABC[3]/self.gradPreEmphHzperDACC), color='blue', bold=True)
      self.dataMagPlot.plot(self.ECCfitx,self.ECCfity, name='FWHMfit',pen=self.bpen)

  def fitECCData(self,b1,data, logSpace=False, nTimeConstants=1, VaryBaseline=False):
      """Fits ECC data with multiexponetial, up to 3 timeconstants and a baseline"""
      if logSpace:
        self.ECCfitx =np.logspace(-4,1, num=self.nfitpoints)    #generate RF pulse amplitudes for fit plot
      else:
        self.ECCfitx =np.arange(self.nfitpoints) * np.amax(b1) * 1.1 /self.nfitpoints  #generate RF pulse amplitudes for fit plot 
      self.ECCfity=np.zeros(self.nfitpoints)
      params=multiExp.initialize (t=b1, s=data, nTimeConstants=nTimeConstants,VaryBaseline=VaryBaseline)
      pdicti=params[0] #parameter dictionary
      plist=params[1] #parameter list
      fitoutput = lmfit.minimize(multiExp.mExp,pdicti,args=(b1,data))
      pdict=fitoutput.params
      self.ECCfity= multiExp.mExp(pdict, self.ECCfitx, np.zeros(len(self.ECCfitx)))
      self.message(lmfit.fit_report(pdict)+'\n')   #add complete fitting report to output report string
      self.ECCt1t2ABC=(float(pdict['t1']),float(pdict['t2']),float(pdict['A']),float(pdict['B']),float(pdict['C']))
      return(fitoutput)
  
  def scanECCParameter(self):
      '''scans a ECC parameter to maximize signal after gradient pulse'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.scanECCparameters=  self.B0CompZeroAmpl+ self.gradPreEmphasisZeroAmpl
      item, ok = QInputDialog().getItem(self, "ECC parameter","Select parameter to be varied", self.scanECCparameters, 0, False)
      if ok :
        scanParam=item
      else:
            return
      startValue, ok = QInputDialog().getDouble(self, "Parameter Start Value","(-10 to 10)",-5, -10, 10,decimals=2)
      if ok :
          pass
      else:
        return
      endValue, ok = QInputDialog().getDouble(self, "Parameter End Value","(-10 to 10)",5, -10, 10,decimals=2)
      if ok :
        pass
      else:
        return
      nsteps, ok = QInputDialog().getInt(self, "number of steps","1 to 1000",100, 1, 1000)
      if ok :
        pass
      else:
        return
      parameters=np.linspace(startValue, endValue, nsteps)
      self.scannedECCParamArray=np.zeros(nsteps)
      self.ui.cbProtocol.setCurrentText('scanECCParam')
      self.openProtocol()
      if self.ui.chbSetObserveFreqToCenterFreq.isChecked():
            self.setObsFrequency()
            self.TNMR.currentFile.SetNMRParameter("Observe Freq.", '{:.6f}MHz'.format(self.TNMR.ObsFreq/10**6))
      self.message('Scanning ECC parameter {}; start={}, stop={}, nsteps={}'.format(scanParam, startValue,endValue, nsteps), bold=True,ctime=False, color='red')
      for i,pvalue in enumerate(parameters):
          app.processEvents()
          self.TNMR.currentFile.SetNMRParameter(scanParam, '{:.2f}'.format(pvalue))
          self.runCurrentTNMRFile() 
          self.dataArrayDimen=(self.TNMR.currentFile.GetNDSize(1),self.TNMR.currentFile.GetNDSize(2),self.TNMR.currentFile.GetNDSize(3),self.TNMR.currentFile.GetNDSize(4))
          self.tntData=self.getTNMRdata(self.dataArrayDimen)
          fidAmp=np.sum(np.absolute(self.tntData[:,0,0,0]))
          sfreq=-(np.fft.fftshift(np.fft.fftfreq(self.tntData.shape[0], self.TNMR.DwellTime)))
          psFFTData=np.fft.fftshift(np.fft.fft(self.tntData[:,0,0,0]))
          spectra= np.absolute(psFFTData)
          normalizedspectra =spectra/np.sum(spectra)
          avFreq=np.average(sfreq,weights=normalizedspectra)
          pkwidth=np.sqrt(np.sum(normalizedspectra*(sfreq-avFreq)**2)) 
          print ('pvalue=', pvalue, ', avFreq=', avFreq, ', peak width(Hz)=', pkwidth)
          self.scannedECCParamArray[i]= fidAmp
      paramPlot=plotWindow(self)
      paramPlot.dplot.plot(parameters,self.scannedECCParamArray)
      paramPlot.show()
      self.TNMR.currentFile.SetNMRParameter(scanParam, '{:.2f}'.format(0))
      # self.ui.rbPSDataSpectra.setChecked(True) #set PSData plot to display spectra      
      # self.plotData(self.tntData)
      # self.ui.dockPSData.setFloating(True)
      # self.setPSDataPhase()
      # self.ui.leFIDFWHM.setText('{:6.2F}'.format(self.FirstPeakFWHM))
      # self.ui.pbFID.setStyleSheet("background-color: rgb(240, 240, 240)") 
       
  def loadECCFile(self,ECCFile=''):
    '''Open ascii Eddy Current COrrection (ECC) file and load into TNMR'''
    if ECCFile=='' or ECCFile==False:
      f, ft = QFileDialog.getOpenFileName(self,'Enter ECC filename', self.studyDirectory, "Tecmag ECC Files (*.dat)")        #Note self.FileName is a qString not a string
      if f=='':
          return
      file=str(f)
    else:
      file=ECCFile
    self.currentECCFile=file
    f = open(file , "r") #saving text version of recipe file
    with open(file, 'r') as fp:
        lines = fp.readlines()
        for line in lines:
            key=line[0:line.find('=')]
            valuestring=line[line.find('=')+1:-1]
            if key in self.B0CompLabels.keys():
                self.B0CompLabels[key].setText(valuestring)
                self.B0CompLabels[key].setStyleSheet("background-color: rgb(200, 200, 200)")       #set background to gray
                if  np.absolute(float(valuestring))!=self.TNMR.B0CompValuesDefault[key]: 
                    self.B0CompLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if > 0
                if key.find('T')==-1:
                    self.TNMR.currentFile.SetNMRParameter(key, valuestring)
                else:             
                    self.TNMR.currentFile.SetNMRParameter(key, '{:6.4f}m'.format(float(valuestring)*1000))       #if parameter is a time constant convert to ms and add an m    
            else:
              if key in self.gradPreEmphasisLabels.keys():
                self.gradPreEmphasisLabels[key].setText(valuestring)
                if np.absolute(float(valuestring))!=self.TNMR.gradPreEmphasisValuesDefault[key]: 
                    self.gradPreEmphasisLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if > 0
                if key.find('T')==-1:
                    self.TNMR.currentFile.SetNMRParameter(key, valuestring)
                else:             
                    self.TNMR.currentFile.SetNMRParameter(key, '{:6.4f}m'.format(float(valuestring)*1000))       #if parameter is a time constant convert to ms and add an m    
    f.close()
    self.message('Loaded ECC file:{}'.format(self.currentECCFile)) 
          
  def saveCurrentECCFile(self,ECCFile=''):
    '''Save current value of 0 compensation and gradient pre-emphasis in ascii file with current date appended'''
    if ECCFile=='' or ECCFile==False:
      f, ft = QFileDialog.getSaveFileName(self,'Enter ECCFile filename', self.studyDirectory, "Tecmag ECCFile Files (*.dat)")        #Note self.FileName is a qString not a string
      if f=='':
          return
      file=str(f)
    else:
      file=ECCFile
    now=datetime.now()
    ft=now.strftime("%Y%m%d_%H%M") 
    self.NMRECCFile=file.replace('.dat','') + ft+ '.dat'  #adding date at end of filename
    f = open(self.NMRECCFile , "w") #saving text version of recipe file
    f.write('[B0 Compensation]\n')
    for key in self.TNMR.B0CompValues:
        f.write('{}={}\n'.format(key, self.TNMR.B0CompValues[key]))
    f.write('[Gradient PreEmphasis]\n')
    for key in self.TNMR.gradPreEmphasisValues:
        f.write('{}={}\n'.format(key, self.TNMR.gradPreEmphasisValues[key]))
    f.close()
    self.message('Saved current ECC in: {}'.format(self.NMRECCFile)) 
    
  def setECCtoDefault(self):
    self.TNMR.setB0CompGradPreEmphToDefault()
     #update gradient pre-emphasis table, higlight used parameters in green
    for key in self.B0CompLabels:
        self.B0CompLabels[key].setText('{:6.4f}'.format(self.TNMR.B0CompValues[key]))
        self.B0CompLabels[key].setStyleSheet("background-color: rgb(200, 200, 200)")       #set background to gray
        if np.absolute(self.TNMR.B0CompValues[key])>0 and key.find('T')==-1: 
            self.B0CompLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if > 0
    for key in self.gradPreEmphasisLabels:
        self.gradPreEmphasisLabels[key].setText('{:6.4f}'.format(self.TNMR.gradPreEmphasisValues[key]))
        self.gradPreEmphasisLabels[key].setStyleSheet("background-color: rgb(200, 200, 200)")       #set background to gray 
        if np.absolute(self.TNMR.gradPreEmphasisValues[key])>0 and key.find('T')==-1: 
            self.gradPreEmphasisLabels[key].setStyleSheet("background-color: rgb(100, 255, 100)")       #set background to green if > 0
    self.message('B0 Comp. and Grad. Preemp. reset to defaults', color='red', bold=True)

#***********RF Power Calibrations***************
  def runRFTxCal(self):
      '''Runs calibration prcedure to determine RF transmit power by running through an array of RF attenuations and fitting with a damped sinusoid'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.ui.pbRFTxCal.setStyleSheet("background-color : lightgreen")
      app.processEvents()      
      self.ui.cbProtocol.setCurrentText('RFTxCal')        #Sets protocol to scout and loads SCOUT template
      self.openProtocol()
      self.PSUpdateRun()
      #self.processRFTxCal()
      self.ui.pbRFTxCal.setStyleSheet("background-color: rgb(240, 240, 240)")
      
  def processRFTxCal(self): 
          '''Process RF calibration data'''
          self.RFTxCalData=self.tntData[:,:,0,0] #FIDs versus RF transmit power
          self.fftRFTxCalData=np.fft.fftshift(np.fft.fft(self.RFTxCalData, axis=0),axes=0)      #Fourier transfrom, find and phase peak, integrate
          self.RFTxCalPeakIndex=np.argmax(np.abs(self.fftRFTxCalData[:,4]))
          dphase=np.angle(self.fftRFTxCalData[self.RFTxCalPeakIndex,4])
          self.ui.leRFCalinfo.setText('Peak located at {}, phased adjust={:.2f}'.format(self.RFTxCalPeakIndex,dphase))
          self.fftRFTxCalData=self.fftRFTxCalData*np.exp(-1j*dphase)
          spectraReal=self.fftRFTxCalData.real
          self.RFSignal=np.trapz(spectraReal[self.RFTxCalPeakIndex-10:self.RFTxCalPeakIndex+10], axis=0)    #Integrate about largest peak
          #self.RFSignal=np.trapz(self.RFTxCalData.real, axis=0)
          self.RFSignal/=self.RFSignal.max()  #normalize
          self.rfAttnArray=np.fromstring(self.TNMR.currentFile.GetTable('rfAttn'), sep=' ')
          self.b1MagArray=(10**((60-self.rfAttnArray)/20))/10     #B1 amplituse normalized so 0attn with max DAC output=100   
          if self.ui.sbRFCalnFitPoints.value()==0 or self.ui.sbRFCalnFitPoints.value()>len(self.RFSignal):  #set number of points to fit
              npoints=len(self.RFSignal)
              self.ui.sbRFCalnFitPoints.setValue(npoints)
          else:
              npoints=self.ui.sbRFCalnFitPoints.value()
          self.ui.sbRFCalSpectra.setMinimum(-1)
          self.ui.sbRFCalSpectra.setMaximum(npoints-1)
          self.fitRFAttnData(self.b1MagArray[0:npoints],self.RFSignal[0:npoints])
          self.ui.pltRFCal.clear()
          self.ui.pltRFCal.setLabel('bottom','B1(%max)')
          self.ui.pltRFCal.setLabel('left', 'Signal')
          self.ui.pltRFCal.plot(self.b1MagArray[0:npoints],self.RFSignal[0:npoints], symbol='x')
          self.ui.pltRFCal.plot(self.fitx,self.fity, pen=self.gpen)
          self.ui.sbPSDataSlice.setMaximum(npoints)
          self.ui.dockRFCalibrations.setFloating(True)
          self.ui.lblRFAttn90Cal.setText('{:6.2F}'.format(self.RFAttn90Cal))
          self.ui.lblRFAttn180Cal.setText('{:6.2F}'.format(self.RFAttn180Cal))
          self.ui.leRFAttn90Cal.setText('{:6.2F}'.format(self.RFAttn90Cal))
          self.ui.leRFAttn180Cal.setText('{:6.2F}'.format(self.RFAttn180Cal))
          
  def plotRFTxCal(self): 
          '''plot RF calibration data'''
          self.ui.pltRFCal.clear()
          self.ui.pltRFCal.setLabel('bottom','Frequency')
          self.ui.pltRFCal.setLabel('left', 'Signal')
          self.ui.pltRFCal.getViewBox().enableAutoRange(axis='y', enable=True)
          self.ui.pltRFCal.addLegend()
          if self.ui.rbRFCalPlotSpectra.isChecked():
            data=self.fftRFTxCalData
          else:
            data=self.RFTxCalData
          if self.ui.sbRFCalSpectra.value()==-1:
              for i in range(self.fftRFTxCalData.shape[1]):
                  p=pg.mkPen(pg.intColor(i), width=2)
                  if self.ui.rbPlotRfcalReal.isChecked():
                      self.ui.pltRFCal.plot(data.real[:,i], pen=p, name='{}'.format(self.rfAttnArray[i]))
                  if self.ui.rbPlotRfcalImag.isChecked():
                      self.ui.pltRFCal.plot(data.imag[:,i], pen=p, name='{}'.format(self.rfAttnArray[i]))
                  if self.ui.rbPlotRfcalMag.isChecked():
                      self.ui.pltRFCal.plot(np.absolute(data[:,i]), pen=p, name='{}'.format(self.rfAttnArray[i]))
          else:
              i= self.ui.sbRFCalSpectra.value()
              p=pg.mkPen(pg.intColor(i), width=2)
              if self.ui.rbPlotRfcalReal.isChecked():
                    self.ui.pltRFCal.plot(data.real[:,i], pen=p, name='{}'.format(self.rfAttnArray[i]))
              if self.ui.rbPlotRfcalImag.isChecked():
                    self.ui.pltRFCal.plot(data.imag[:,i], pen=p, name='{}'.format(self.rfAttnArray[i]))
              if self.ui.rbPlotRfcalMag.isChecked():
                    self.ui.pltRFCal.plot(np.absolute(data[:,i]), pen=p, name='{}'.format(self.rfAttnArray[i])) 
                    
  def fitRFAttnData(self,b1,data):
      """Fits RFAttn data with sinusoid, calls fitting routines in dampedSin Signal = a*(sin(pi/2*t/t90) * np.exp(-t/tau))"""
      self.fitx =np.arange(self.nfitpoints) * np.amax(b1) * 1.1 /self.nfitpoints  #generate RF pulse amplitudes for fit plot
      self.fity=np.zeros(self.nfitpoints)
      params=dampedSin.initialize (t=b1, s=data)
      pdicti=params[0] #parameter dictionary
      plist=params[1] #parameter list
      fitoutput = lmfit.minimize(dampedSin.dSin,pdicti,args=(b1,data))
      pdict=fitoutput.params
      self.fity= dampedSin.dSin(pdict, self.fitx, np.zeros(len(self.fitx)))
      self.message(lmfit.fit_report(pdict)+'\n')   #add complete fitting report to output report string
      self.b90Cal=float(pdict['t90'])
      self.b1Tau=float(pdict['tau'])
      self.RFAttn90Cal=-(np.log10(self.b90Cal*10)*20-60)
      self.RFAttn180Cal=-(np.log10(2*self.b90Cal*10)*20-60)
      self.message("B190(%max)= {:.2f}, B190(uT)={:.2f}, 1/tau={:.2e}, RFAttn90Cal(dB)={:.2f}".format(self.b90Cal,1E6*np.pi/(2*self.Gamma*self.RFCalPW),1/self.b1Tau, self.RFAttn90Cal), color='green', bold=True)
      return(fitoutput)           
#*************Shim Routines*************************              

  def loadShimFile(self,shimFile=''):
    '''Open ascii shim file and load into TNMR'''
    if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
    app.processEvents()
    if shimFile=='' or shimFile==False:
      f, ft = QFileDialog.getOpenFileName(self,'Enter shim filename', self.studyDirectory, "Tecmag Shim Files (*.shm)")        #Note self.FileName is a qString not a string
      if f=='':
          return
      file=str(f)
    else:
      file=shimFile
    self.currentShimFile=file
    for i, shim in enumerate(self.currentShims):
        self.shimValue[i]=self.TNMR.App.GetOneShim(shim)
    f = open(file , "r") #saving text version of recipe file
    with open(file, 'r') as fp:
        lines = fp.readlines()
        for line in lines:
            if line.find('[ShimTerms]')>=0:     #do not look at the [ShimTerms section
                break
            for shim in self.currentShims:
                if( line.find(shim) >= 0 ):
                    self.currentShimValues[shim] = int(line.split('=')[-1].strip())
    f.close()
    self.setShimValues()
    self.message('Loaded shim file:{}'.format(self.currentShimFile)) 
          
  def saveCurrentShimFile(self,shimFile=''):
    '''Save current value of shims in ascii file with current date appended'''
    if shimFile=='' or shimFile==False:
      f, ft = QFileDialog.getSaveFileName(self,'Enter shim filename', self.studyDirectory, "Tecmag Shim Files (*.shm)")        #Note self.FileName is a qString not a string
      if f=='':
          return
      file=str(f)
    else:
      file=shimFile
    ft=time.time.strftime("%Y%m%d_%H%M")
    self.NMRShimFile=file+ft
    for i, shim in enumerate(self.currentShims):
        self.shimValue[i]=self.TNMR.App.GetOneShim(shim)
    f = open(self.NMRShimFile , "w") #saving text version of recipe file
    f.write('[Shims]\n')
    for i, shim in enumerate(self.currentShims):
        f.write('{}={}\n'.format(shim, self.shimValue[i]))
    f.close()
    self.message('Saved current shims in: {}'.format(self.NMRShimFile)) 
    
  def BBShim(self):
      subprocess.call(r'wscript.exe C:\TNMR\scripts\AutoShim_BergerBraun_full_NOSPIN.vbs')

  def zeroShims(self):
    '''zero Shims procedure'''
    for shim in self.currentShims:
        self.TNMR.App.SetOneShim(shim, 0)
    self.getShimValues()
    self.message("Shims zeroed")
    
  def setShimValues(self):
    '''set shim values in TNMR'''
    for shim in self.currentShims:
        self.TNMR.App.SetOneShim(shim,self.currentShimValues[shim])
        self.shimLabels[shim].setValue(int(self.currentShimValues[shim]))
            
  def getShimValues(self):
    '''get and list shim values'''
    for shim in self.currentShims:
        self.currentShimValues[shim]=self.TNMR.App.GetOneShim(shim)
        self.shimLabels[shim].setValue(int(self.currentShimValues[shim]))

  def setShimParameters(self):
    '''Inputs parameters used in shimming'''
    nstep, ok = QInputDialog().getInt(self, "Shim","StepSize", self.ShimStep, 1, 500)
    if ok :
        self.ShimStep=nstep
    else:
        return
    target, ok = QInputDialog().getDouble(self, "Shim","Target", self.ShimPrecision, 0.0001, 0.1,4)
    if ok :
        self.ShimPrecision=target
    else:
        pass
      

  def autoShim(self, zeroshims=False):
    '''Auto Shim procedure, runs the built in TNMR shim procedure with selected pulse sequence'''
#    if self.shimmingInProgress:
    if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
    self.ui.pbAutoShim.setStyleSheet("background-color: lightgreen")
    app.processEvents()
    item, ok = QInputDialog().getItem(self, "Shim start:","Choose starting state", ('Use Current Shims','Zero Shims', 'Load Shim File'), 0, False)
    if ok :
        if item=='Zero Shims':
            self.zeroShims()
        if item=='Load Shim File':
            self.loadShimFile()
    else:
        self.ui.pbAutoShim.setStyleSheet("background-color: rgb(240, 240, 240)") 
        return
    self.ShimUnits=[]       #list of shimUnits aquired during the shimming process
    app.processEvents()
    item, ok = QInputDialog().getItem(self, "Shim sequence:","Choose shim sequence", ('Hard Pulse', 'Slice select axial', 'Slice select sagittal','Slice select coronal', 'Current protocol'), 0, False)
    if ok :
        if item=='Hard Pulse':
            self.ui.cbProtocol.setCurrentText('ShimFIDHP')
            self.openProtocol()
        if item=='Slice select axial':
            self.ui.cbProtocol.setCurrentText('ShimFIDSS')
            self.openProtocol()
            self.ui.leGradientOrientation.setText('{}'.format('XYZ'))
            self.ui.cbGradOrientation.setCurrentText(self.TNMR.getScanOrientation('XYZ'))
        if item=='Slice select sagittal':
            self.ui.cbProtocol.setCurrentText('ShimFIDSS')
            self.openProtocol()
            self.ui.leGradientOrientation.setText('{}'.format('YZX'))
            self.ui.cbGradOrientation.setCurrentText(self.TNMR.getScanOrientation('YZX'))
        if item=='Slice select coronal':
            self.ui.cbProtocol.setCurrentText('ShimFIDSS')
            self.openProtocol()
            self.ui.leGradientOrientation.setText('{}'.format('XZY'))
            self.ui.cbGradOrientation.setCurrentText(self.TNMR.getScanOrientation('XZY'))
    else:
        self.ui.pbAutoShim.setStyleSheet("background-color: rgb(240, 240, 240)") 
        return

    self.message('Auto Shimming started', bold=True,ctime=True)
    self.TNMR.App.SetAutoShimParameters (self.ShimDelay, self.ShimPrecision, self.ShimLockorFid, self.ShimStep)
    self.TNMR.App.ActivateShims(self.autoShimList)
    self.TNMR.App.StartShims()
    self.shimmingInProgress=True
    while self.TNMR.App.CheckShimProgress:
         app.processEvents()
    self.shimmingInProgress=False
    self.TNMRbusy=False
    self.runFID()
    self.message('Auto Shimming finished', bold=True,ctime=True)
    self.ui.pbAutoShim.setStyleSheet("background-color: rgb(240, 240, 240)")    
        
  def quickShim(self, zeroshims=False):
    '''Abbreviated Shim procedure'''
    self.ShimUnits=[]       #list of shimUnits aquired during the shimming process
    if zeroshims:
        self.zeroShims()
    Delay ="1s"
    Precision = 0.02
    LockorFid = 1
    Step = "100"
    app.processEvents()
    self.message('Shimming started')
    self.TNMR.App.SetAutoShimParameters (Delay, Precision, LockorFid, Step)
    self.TNMR.App.ActivateShims(self.quickShimList)
    self.TNMR.App.StartShims()
    self.shimmingInProgress=True
    while self.TNMR.App.CheckShimProgress:
         app.processEvents()    
    self.shimmingInProgress=False

  def TNMRShim(self, shimType="BBnospin", NMRShimFile=None, waitUntilDone=True, autoSave=True, startShims='zero'):
      '''Starts shim procedure'''
      if NMRShimFile==None:   #If no filename is given open dialog box and get one
            f, ft = QFileDialog.getOpenFileName(self,'Open NMR shim file', self.studyDirectory, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
            if f=='':
                pass
            else:
                NMRShimFile=str(f)
            item, ok = QInputDialog().getItem(self, "Starting shims","enter initial shim state", self.initialShims, 0, False)
            if ok :
              startShims=item
      if self.ui.rbImmediate.isChecked() or self.recipeRunning:     #execute shim procedure either in immediate or recipeRunning mode
          self.message("Shimming")
          self.shimmingInProgress=True
          if NMRShimFile != '':
              shimfile=self.addPathname(NMRShimFile)
              self.TNMR.openFile(shimfile)
              self.studyDirectory=os.path.dirname(NMRShimFile)
          #subprocess.call(r'wscript.exe C:\TNMR\scripts\AutoShim_BergerBraun_full_NOSPIN.vbs')
          #subprocess.Popen(r'wscript.exe C:\TNMR\scripts\AutoShim_BergerBraun_full_NOSPIN.vbs')
          if startShims.lower()=='zero':
              self.zeroShims()
          self.autoShimBBnoSpin()
          self.shimmingInProgress=False
          if waitUntilDone:
                  while self.TNMR.checkAcquisition():
                      self.pause(2)
                      if self.recipeAbort:
                          self.message('Aborting TNMR Shim execution')
                          self.TNMR.abort()
                          return
                  if autoSave:
                    if NMRShimFile != '':  
                        fn=shimfile.replace('.tnt', '_Shims' +'.tnt')
                        if self.GradientsOn:
                            sfn=shimfile.replace('.tnt', 'GradOn.shm')
                        else:
                            sfn=shimfile.replace('.tnt', 'GradOff.shm')
                        try:
                            self.TNMR.saveCurrentFile(filename=self.addPathname(fn))  #Save tnt file
                        except:
                            pass
                        try:
                            self.saveCurrentShimFile(shimFile=self.addPathname(sfn))        #save shim file
                        except:
                            pass

      else:
          self.ui.txtRecipe.append('<b>\aTNMRShim</b>(shimType="{}", NMRShimFile="{}", waitUntilDone={}, autoSave={}, startShims="{}")'.format(shimType, NMRShimFile.replace(self.CRpathName,''), waitUntilDone, autoSave, startShims))
          self.ui.txtRecipe.append('')
          
#**********TNMR commands*******************                            
  def saveTNMRfilewDateID(self, fileID=''):
    '''Save TNMR file with finish date and otional ID'''
    try:
        ftime=datetime.strptime(self.TNMR.finishTime,'%A,%B %d,%Y:%H:%M:%S')
    except:
        try:
            ftime=datetime.strptime(self.TNMR.finishTime,'%A, %B %d, %Y %H:%M:%S')
        except:
            self.message('Cannot find file finish time')
    ft=ftime.strftime("%Y%m%d_%H%M")
    fn=self.NMRfileName.replace('.tnt', '_' + ft +'.tnt')     #add finish date time to filename
    self.message('Saved file: ' + fn+fileID)
    self.TNMR.saveCurrentFile(filename=fn+fileID)
               
  def TNMRZG(self):
      '''Runs TNMR zero and go command which starts a pulse sequence'''
      if self.ui.rbImmediate.isChecked() or self.recipeRunning:
          self.TNMR.zg()
      else:
          self.ui.txtRecipe.append('<b>\aTNMR.zg</b>()')
          self.ui.txtRecipe.append('')
          
  def TNMRstop(self):
      if self.ui.rbImmediate.isChecked() or self.recipeRunning:
          self.TNMR.stop()
      else:
          self.ui.txtRecipe.append('<b>\aTNMR.stop</b>()')
          self.ui.txtRecipe.append('')
          
  def TNMRAbort(self):
      '''Immeadialy aborts TNMR'''
      try:
          self.TNMR.abort()
          self.message('TNMR Aborted', bold=True,ctime=True, color='red')
          self.recipeAbort=True
      except:
          self.message('Abort cannot be implemnted')
                              
  def TNMRRepeatScan(self):
      '''runs TNMR repeat scan command which runs a sequence continually'''
      self.TNMR.rs()
            
  def TNMRCheckAcquisition(self):
      '''sets flag self.TNMRbusy = Tru if busy, False if not busy taking data'''
      self.TNMRbusy=self.TNMR.checkAcquisition()
      if self.shimmingInProgress:       #While running shimming script, TNMR will not respond o queries
           self.TNMRbusy==True
      self.setTNMRbusyflag(self.TNMRbusy)
      if self.TNMRbusy==False and self.TNMRbusyOld==True:
          self.TNMRjustFinished=True 
      self.TNMRbusyOld=self.TNMRbusy
      
  def setTNMRbusyflag(self, flag):
      '''sets flag to indicate TNMR is busy and changes label color'''
      if flag:
          self.ui.lblTNMRStatus.setText('TNMR busy')
          self.ui.lblTNMRStatus.setStyleSheet( "background-color : red") 
      else:
          self.ui.lblTNMRStatus.setText('TNMR idle')
          self.ui.lblTNMRStatus.setStyleSheet("background-color : lightgreen")

  def chkDeleteTNMRData(self):
      '''Flag to close TNMR file after run and autosave'''
      if self.ui.chkDeleteTNMRDataAfterAutoSave.isChecked():
          self.closeTNMRFileAfterUse=True
      else:
          self.closeTNMRFileAfterUse=False
      
  def TNMRString2Float(self,s):
      '''Converts Techmag string s with units to floats'''
      if s.find('u')!=-1:
          val=10**-6*float(s.replace('u',''))
      if s.find('m')!=-1:
          val=10**-3*float(s.replace('m',''))  
      if s.find('s')!=-1:
          val=float(s.replace('s',''))
      return val 
  
#***************Recipe Commands**************
                                      
  def openRecipeFile (self):
    '''opens an ascill recipe file, formats so comands are in bold and there is a line start symbol'''
    f = QFileDialog.getOpenFileName(self,"Open Recipe File", self.studyDirectory, "Recipe Files (*.rcp)")
    fileName=f[0]
    if fileName=='':  #if cancel is pressed return
      return None
    self.recipeFileName=fileName
    self.ui.lblRecipeFileName.setText(fileName)
    f = open(str(fileName), 'r')
    self.ui.txtRecipe.clear()
    for line in f:
      if line.find('\a') !=-1:
              line=line.replace('\a', '<b>\a', 1)
              line=line.replace('(', '</b>(', 1)
      if line.find('#') !=-1:
              line=line.replace('#', '<b>#', 1)
              line=line.replace(':', '</b>:', 1)
      self.ui.txtRecipe.append(line.strip('\n')) #
                
  def saveRecipeFile (self):
    f = QFileDialog.getSaveFileName(parent=None, caption="Recipe File Name",filter="*.rcp")
    if f[0]=='':
          return 'cancel'
    else:
        self.recipeFileName=str(f[0])

    f = open(self.recipeFileName , "w") #saving text version of recipe file
    f.write(self.ui.txtRecipe.toPlainText())
    #f.write(self.ui.txtRecipe.toHtml())
    f.close()
    self.ui.lblRecipeFileName.setText(self.recipeFileName) 
    
  def executeRecipe(self):
    '''executes a recipe, takes text from recipe textbox and executes it line by line in Python using exec(line) '''
    if self.recipePreCheck()==False:
        return
    self.recipeAbort=False      #set abort flag to False, abort if it is True
    self.recipeRunning=True
    self.nUpdates=1
    self.startTime=time.time()
    #self.ui.rbAddtoRecipe.setChecked(True)      #want to be recipe edit mode while recipe is running
    self.currentRecipeHTML=self.ui.txtRecipe.toHtml()
    self.currentRecipe=self.ui.txtRecipe.toPlainText().replace('\a','self.').split('\n')     #recipe is a tuple of commands
    self.message('***Starting Recipe***',color='blue')
    self.ui.lblRecipeRunning.setText('Recipe Running')
    self.ui.lblRecipeRunning.setStyleSheet("QLabel { background-color : rgb(0,255,0)}")
    self.currentRecipeStep=0
    for icommand, command in enumerate(self.currentRecipe):
        if self.recipeAbort==True:
            self.recipeRunning=False
            self.message('Recipe aborted')
            break
        if command.strip() != ''  : #execute command if it has something in it and it does not start with a comment sign
            self.currentRecipeStep+=1
            app.processEvents()     #check events especially abort flag
            self.iCommand=icommand      #used to index line to set highlight in recipe editor
            self.message(command)
            self.addGreenArrowToRecipe(self.iCommand)
            self.monitorInstruments()       #monitor instruments in case command is too short
            exec(command)
    self.endRecipe()
    self.recipeRunning=False

  def endRecipe(self):
    '''housekeeping at the end of a recipe'''
    self.ui.lblRecipeRunning.setText('Recipe Completed')
    self.ui.lblRecipeRunning.setStyleSheet("QLabel { background-color : rgb(205,219,255)}")
    #self.ui.rbAddtoRecipe.setChecked(True)
    self.ui.txtRecipe.clear()       #Clean up text and get rid of arrows
    self.ui.txtRecipe.insertHtml(self.currentRecipeHTML)
    self.currentRecipeStep=0
    self.iCommand=-1
    if self.recipeFileName != '':       #Save monitor data to a file
        try:
            self.dataPlot.saveData(self.recipeFileName)
        except:
            raise
    self.message('***Recipe Completed***',color='blue', ctime=True)

  def abortRecipe(self): 
    self.recipeAbort=True
    self.ui.pbAbortRecipe.setStyleSheet("QLabel { background-color : rgb(0,255,0)}")
    self.ui.pbAbortRecipe.setText('Aborting')

  def addGreenArrowToRecipe(self, nline):
    '''adds an arrow to indicate which line of the recipe is executing'''
    self.ui.txtRecipe.moveCursor(QTextCursor.Start)
    cursor = QTextCursor(self.ui.txtRecipe.document().findBlockByLineNumber(nline))
    self.ui.txtRecipe.setTextCursor(cursor)
    self.ui.txtRecipe.insertHtml('<p><span style="color:green">&#8594;</span></p>')
    self.ui.txtRecipe.setFocus()
                
  def clearRecipe(self): 
    self.ui.txtRecipe.clear()
    self.ui.txtRecipe.append('# <b>MRIControl Recipe: </b>' + time.strftime("%c")) 
    self.ui.txtRecipe.append('')
    self.ui.lblRecipeFileName.setText('')

  def addFileToRecipe(self):
      '''adds pulse sequence file to queue'''
      f, ft = QFileDialog.getOpenFileName(self,' PS file to add to Queue', self.studyDirectory, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
      if f=='':
        return
      else:
            file=str(f)
            item, ok = QInputDialog().getItem(self, "TNMR file","autoSave after running", self.TrueOrFalse, 0, False)
            if ok :
                if item=='True':
                    autoSave=True
                    waitUntilDone=True
                else:
                    autoSave=False
            ct, ok = QInputDialog().getText(self, "Append Comment to PS file comment","Comment=", text='')
            if ok :
                comment=ct
            else:
                comment=''
      runtime=''    #str(timedelta(seconds=round(self.TNMR.currentFile.GetSequenceTime)))
      self.ui.txtRecipe.append('<b>\aRunTNMRfile</b>(file="{}", autoSave={},waitUntilDone={},comment="{}", runtime="{}")'.format(file,  autoSave, waitUntilDone, comment, runtime))
      self.ui.txtRecipe.append('')
      
  def addRecipeCommand(self):
    recipeCommand=self.ui.cbAddRecipeCommand.currentText()
    if recipeCommand == 'EndRecipe':
            print('EndRecipe')
      
  def showAciveRecipe(self):
      self.clearRecipe()
      self.ui.txtRecipe.setHtml(self.currentRecipeHTML)

  def recipePreCheck(self):
    '''Recipe precheck: check files exist, temperatures are within range'''
    lines=self.ui.txtRecipe.toPlainText().replace('\a','self.').split('\n')     #recipe is a tuple of commands
    nCommand=0
    passCheck=True
    for icommand, command in enumerate(lines):
        if command.strip() != '' and command.strip()[0] != '#': #skip whitespace and comments
            if command.find('openTNMRfile(file=')>=0:
                fs=command.find(r'openTNMRfile(file="')+ len(r'openTNMRfile(file="')
                fe=command.find(r'",')
                fname=command[fs:fe]
                if os.path.isfile(fname)==False:
                    self.message('Line{}: File {} does not exist'.format(icommand,fname), color='red')
                    passCheck=False
            if command.find('setTemperature(temperature=')>=0:
                fs=command.find('setTemperature(temperature=')+len('setTemperature(temperature=')
                fe=command.find(',')
                temperature=float(command[fs:fe])
                if temperature <self.TemperatureNMRMin or temperature >self.TemperatureNMRMax:
                    self.message('Line{}: temperature {:.2f} is out of bounds'.format(icommand, temperature), color='red')
                    passCheck=False
            if command.find('N2Temp=')>=0:
                fs=command.find('N2Temp=')+len('N2Temp=')
                fe=command.find(',',fs,-1)
                N2Temp=float(command[fs:fe])
                if N2Temp <self.N2TempMin or N2Temp >self.N2TempMax:
                    self.message('Line{}: N2 temperature {:.2f} is out of bounds'.format(icommand, N2Temp), color='red')
                    passCheck=False
        nCommand+=1
    if passCheck:
        self.message('Recipe PreCheck OK', color='green')
        return True
    else:
        self.message('Recipe PreCheck Fail', color='red')
        return False
           
  def formatRecipe(self, recipe):
      '''adds formating, eg commands in bold, for easy reading'''
      lines=recipe.split('\n')
      for line in lines:
          if line.find('\a') !=-1:
              line.replace('\a', '<b>\a', 1)
              line.replace('(', '</b>(', 1)
          if line.find('#') !=-1:
              line.replace('#', '<b>#', 1)
              line.replace(':', '</b>:', 1) 
      frecipe='\n'.join(lines)
      return frecipe    
      
  def PSUpdateRun(self):
      '''Updates current pulse sequence in TNMR and then runs it'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.recipeAbort=False    #clear abort flag if set
      if self.ui.chbUpdateBeforeRun.isChecked():
          self.updatePS()       #update current pulse sequence with entries in pyMRI
 #     self.TNMR.compilePS
      #self.TNMR.getPSparams()
      self.ui.leExpectedAcqTime.setText(str(timedelta(seconds=round(self.TNMR.currentFile.GetSequenceTime))))
      self.message('Running ' + self.NMRfileName , bold=True,ctime=True, color='green')
      self.runCurrentTNMRFile()
      self.TNMR.getPSparams()
      self.dataArrayDimen=(self.TNMR.currentFile.GetNDSize(1),self.TNMR.currentFile.GetNDSize(2),self.TNMR.currentFile.GetNDSize(3),self.TNMR.currentFile.GetNDSize(4))
      self.tntData=self.getTNMRdata(self.dataArrayDimen)
      self.currentRawDataRealmax=np.amax(np.abs(self.tntData.real))
      self.currentRawDataImagmax=np.amax(np.abs(self.tntData.imag))
      self.plotData(self.tntData)
      if self.setupdict['PostProcessRoutine']!='':
          postprocess='self.'+self.setupdict['PostProcessRoutine']
          exec(postprocess)
      # if self.ui.cbProtocol.currentText()=='SCOUT':
      #   self.processScout(nRF=-1, raw=False)
      if self.setupdict['DisplayImages']:
        self.displayImage()
      self.message('Completed:' + self.NMRfileName, bold=True,ctime=True, color='green')
      if self.currentRawDataRealmax<self.maxTecmagDACcount and  self.currentRawDataImagmax<self.maxTecmagDACcount:
          self.message('Max signal value={:.2f}+i*{:.2f}'.format(self.currentRawDataRealmax, self.currentRawDataImagmax) , bold=True,ctime=True, color='green')
      else:
           self.message('Overflow warning: Max value={:.2f}+i*{:.2f}'.format(self.currentRawDataRealmax, self.currentRawDataImagmax) , bold=True,ctime=True, color='red')
               
  def  addPStoQueue(self):
      '''Updates and Saves current Pulse Sequence file and adds to queue'''
      # if  self.ui.leSequenceID.text()=='':
      #   date = time.strftime("%d%b%Y")
      # else:
      #     date=''
      # sid, ok = QInputDialog().getText(self, "Sequence ID","ID to add to filename", text='')
      # if ok :
      #       sid='_'+ str(sid)
      # else:
      #       sid=''
      
      filename=self.ProtocolName + '_' + self.ui.leSequenceID.text()  #sid    #+date
      f, ft = QFileDialog.getSaveFileName(self,'Save PS file to study directory', self.studyDirectory+'//'+filename, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
      if f=='':
        return
      else:
            file=str(f)
            item, ok = QInputDialog().getItem(self, "TNMR file","autoSave after running", self.TrueOrFalse, 0, False)
            if ok :
                if item=='True':
                    autoSave=True
                    waitUntilDone=True
                else:
                    autoSave=False
            ct, ok = QInputDialog().getText(self, "Append Comment to PS file comment","Comment=", text='')
            if ok :
                comment=ct
            else:
                comment=''
      if self.ui.chbUpdateBeforeRun.isChecked():
          self.updatePS()       #update and save pulse sequences
      self.TNMR.saveCurrentFile(filename=file) 
      runtime=str(timedelta(seconds=round(self.TNMR.currentFile.GetSequenceTime)))
      self.ui.txtRecipe.append('<b>\aRunTNMRfile</b>(file="{}", autoSave={},waitUntilDone={},comment="{}", runtime="{}")'.format(file,  autoSave, waitUntilDone, comment, runtime))
      self.ui.txtRecipe.append('')
      
  def  addPSFiletoQueue(self):
      '''Adds existing Pulse Sequence file to the queue, unlike assPStoQuesue it does not immeadiately load the file to TNMR for modification, it is run as is'''
      f, ft = QFileDialog.getOpenFileName(self,'Add PS file to the queue', self.studyDirectory, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
      if f=='':
        return
      else:
            file=str(f)
            item, ok = QInputDialog().getItem(self, "TNMR file","autoSave after running", self.TrueOrFalse, 0, False)
            if ok :
                if item=='True':
                    autoSave=True
                    waitUntilDone=True
                else:
                    autoSave=False
            ct, ok = QInputDialog().getText(self, "Append Comment to PS file comment","Optional Comment=", text='')
            if ok :
                comment=ct
            else:
                comment=''
      runtime=''    #str(timedelta(seconds=round(self.TNMR.currentFile.GetSequenceTime)))
      self.ui.txtRecipe.append('<b>\aRunTNMRfile</b>(file="{}", autoSave={},waitUntilDone={},comment="{}", runtime="{}")'.format(file,  autoSave, waitUntilDone, comment, runtime))
      self.ui.txtRecipe.append('')
      
  def  addSetTemperaturetoQueue(self):
      '''Adds SetTemperataure to Queue'''
      item, ok = QInputDialog().getItem(self, "TNMR file","Wait for Temperature Stable", self.TrueOrFalse, 0, False)
      if ok :
        if item=='True':
            waitUntilDone=True
        else:
                    autoSave=False
      st, ok = QInputDialog().getDouble(self, "Sets Temperature","Temperature(C)=",20, min=0, max=80)
      if ok :
            temperature=st
      else:
            temperature=20
      self.ui.txtRecipe.append('<b>\asetTemperature</b>(temperature={},waitUntilStable={}, temperatureStableRange=1)'.format(temperature, waitUntilDone))
      self.ui.txtRecipe.append('') 
            
  def addCommandToRecipe(self):
      if self.ui.cbAddRecipeCommand.currentText()=='Set Temperature':
        self.addSetTemperaturetoQueue()
          
  def clearMessages(self):
      self.ui.txtMessages.clear() 
      
  def saveMessages(self):
      pass 
                       
  def saveTNMRfileAs(self):
      '''Saves TNMR file with default filename protocl-finish time'''
      protocol=self.ui.cbProtocol.currentText()+ '_'
      self.TNMR.getPSparams()
      try:      #get pulse sequence finish time
              ftime=datetime.strptime(self.TNMR.finishTime,'%A,%B %d,%Y:%H:%M:%S')
      except:
            try:
                ftime=datetime.strptime(self.TNMR.finishTime,'%A, %B %d, %Y %H:%M:%S')
            except:
               self.message('Cannot find file finish time')
      ft=ftime.strftime("%Y%m%d_%H%M")
      sequenceID=self.ui.leSequenceID.text()
      if sequenceID != '':
          sequenceID+='_'
      suggestedfn= protocol + sequenceID + ft
      f, ft = QFileDialog.getSaveFileName(self,'Save TNMR file', self.studyDirectory+'\\'+suggestedfn, "Tecmag Files (*.tnt)")        #Note self.FileName is a qString not a string
      if f=='':
        return
      else:
        self.saveNMRfileName=f     #self.NMRfileName is complete filename with full path
      self.TNMR.saveCurrentFile(filename=self.saveNMRfileName)    
               
  def runCurrentTNMRFile(self, waitUntilDone=True):
      '''Runs current TNMR file and updates busy flags'''
      if self.TNMRbusy:
        QMessageBox.warning(None, "TNMR Active", "Need to wait")
        return
      self.TNMRjustFinished=False
      self.TNMR.zg()
      self.TNMRStartTime=time.time()
      self.ui.progressbarTNMR.setValue(0)
      if waitUntilDone:
        while self.TNMR.checkAcquisition():
            self.TNMRbusy=True
            self.setTNMRbusyflag(self.TNMRbusy)
            self.TNMRRunTime=time.time()-self.TNMRStartTime
            self.pause(1)
            if self.recipeAbort:
                self.message('Aborting TNMR file execution')
                self.TNMR.abort()
                return
            
  def RunTNMRfile(self, file=None, autoSave=False, waitUntilDone=False, comment='', closeFileAfterUse=True, runtime=''):
    '''Opens and runs TNMR file and optionally runs and saves file. Mainly used in recipes'''
    self.studyDirectory=os.path.dirname(file)
    self.closeActiveFile=False    #do not close on open, will close after use
    self.openTNMRfile(file=file)
    self.runCurrentTNMRFile(waitUntilDone=waitUntilDone)
    #******Finished acquisition*****
    Tav, Tsd =self.recipeStatistics(self.currentRecipeStep)
    stemp='Recipe step={}, Tave(C)={:.3f}, Tstd(C)={:.3f}'.format(self.currentRecipeStep,Tav,Tsd )
    self.message(stemp, color='orange')
    #self.TNMR.setComment('; ' + stemp)    #update comment with average temperature and standard deviation
    #self.ui.lblTNMRComment.setText('{}'.format(self.TNMR.comment)) 
    if autoSave:
        try:      #get pulse sequence finish time and add to end of filename
              self.TNMR.finishTime=self.TNMR.currentFile.GetNMRParameter('Exp. Finish Time')
              ftime=datetime.strptime(self.TNMR.finishTime,'%A,%B %d,%Y:%H:%M:%S')
        except:
            try:
                ftime=datetime.strptime(self.TNMR.finishTime,'%A, %B %d, %Y %H:%M:%S')
            except:
               self.message('Cannot find file finish time')
               ftime=''
        if Tav!= np.nan and self.ui.cbMonitorTemperatures.isChecked()==True:
            ft='_' + '{:.2f}C'.format(Tav) + '_' + ftime.strftime("%Y%m%d_%H%M") +'.tnt'
        else:
            ft='_' + ftime.strftime("%Y%m%d_%H%M") +'.tnt'
        saveFileName=file.replace('.tnt', ft)
        self.TNMR.saveCurrentFile(filename=saveFileName) 
    if closeFileAfterUse:
          self.message('Closing file', color='orange')
          self.pause(2)
          self.TNMR.closeActiveFile()
        
  def recipeStatistics(self, rstep=0):
    '''Calculates ave and std deviation of environmental parameters for recipe step =rstep'''
    try:
        data  =self.dataArray[self.dataArray[:,1] ==rstep]      #pick data from second column that has recipe step=rstep
        tav=np.average(data[:,4])   #pick data from fifth column that hasFO temperature
        tsd=np.std(data[:,4])
        return tav, tsd
    except:
        return np.nan, np.nan
        
  def setObsFrequency(self):
      '''Sets observe frequency to current prescan center frequency'''
      if self.ui.chbSetObserveFreqToCenterFreq.isChecked():
          if self.currentF0 !=0:
              self.TNMR.ObsFreq=self.currentF0
              self.ui.leTMRFobserve.setText('{:.6f}'.format(self.currentF0/10**6))
      
  def changeScanOrientation(self):
      '''if the scan orinetation changes update text and redisplay slice plan'''
      self.ui.leGradientOrientation.setText(self.scanOrientation[self.ui.cbGradOrientation.currentText()])
      self.plotSlicesInScout()
      
  def TNMRnAcqPointsValueChanged(self):
      self.ui.spboxTNMRnAcqPoints.setValue(int(self.ui.spboxTNMRnAcqPoints.value()/64)*64)
      self.nAcqPoints= self.ui.spboxTNMRnAcqPoints.value()
      self.TNMR.DwellTime=self.TNMR.AcqTime/self.nAcqPoints
      self.ui.dspboxDwellTime.setValue(self.TNMR.DwellTime*1000)
      self.ui.leTNMRSW.setText('{:6.2f}'.format(1/(2*self.TNMR.DwellTime)))

  def phaseEncodeValueChanged(self):
      self.ui.spboxPhaseEncodes.setValue(int(self.ui.spboxPhaseEncodes.value()/64)*64)
      
  def regneratePhaseEncodeArray(self,nphases, nacqpoints):
      '''recalculates phase encode aray, +-100 = +- 180deg, defalts to a linear array from positive to negative'''
      endvalue=int(nphases/nacqpoints*100)
      a0=2*endvalue/(nphases-1)
      self.phaseEncodeArray=np.linspace(endvalue-a0,-endvalue,nphases)
     
#**************ROIs**********************************

  # def addSlicePlanROIs(self):
  #   '''Creates ROIs in slice plan windows'''
  #   for sl in range(self.nSlices):      
  #       pgroi=fRectROI(self,[imCoord[0]-roi.dx/2, imCoord[1]-roi.dy/2], [roi.dx, roi.dy],lab,angle=roi.theta, pen=self.roiPen)  #needs work
  #       pgroi.Index=roi.Index
  #       self.pgROIs.append(pgroi)
  #   for roi in self.pgROIs:
  #       self.imvCoronal.getView().addItem(roi)
  #       self.imv.getView().addItem(roi.label)

#*******************Diffusion calculations/fitting*************************************************

  def STbvalue(self,  g=0.1, delta=0.01, Delta=0.01, risetime=0.0001, pulsetype='trap'):
    '''calculates  diffusion b-values according to generalized Stejskal-Tanner equation
     delta=grad pulse duration, Delta=grad pulse separation, risetime is the the grad pulse rise and falltime, all times in s'''
    gamma=self.Gamma
    if pulsetype=='trap':
        epsilon=risetime/delta
        sigma=1-epsilon
        lamda=0.5
        kappa=0.5-sigma/6+epsilon**3/60/sigma**2-epsilon**2/12/sigma
    if pulsetype=='hSin':
        sigma=2/np.pi
        lamda=0.5
        kappa=3.0/8.0    
    b=1E-6*(sigma*gamma*delta*g)**2*(Delta-2*(lamda-kappa)*delta)       #value calculated in SI s/m^2; convert to s/mm^2, exception to SI rule!
    self.message('<b>b-Value calculated using ST formula:</b> {} pulse, risetime(ms)={:.4f}, duration(ms)={:.4f}, pulse spacing(ms){:.4f}'.format(pulsetype, risetime*1000, delta*1000, Delta*1000))
#    bRect=1E-6*(gamma*delta*g)**2*(Delta-delta/3)
    return b    
#***************Picoscope methos*********************
      
  def openPicoscope(self):
      self.pico5000=pico5000MRI()
      self.pico5000.show()
      self.picoscopeIsOpen=True 
      
  def closePicoscope(self):
      try:
          self.pico5000.closePicoscope()
          self.pico5000.close()
      except:
          pass
      self.picoscopeIsOpen=False  
      
  def capturePicoscope(self):
      self.pico5000.picoCapture()

#Image processing and plotting methods************************                 
  def displayImage(self):
      self.imw.activateWindow()
      self.imw.setWindowTitle('Image Display: ' +self.NMRfileName)
      self.imw.fileName=self.NMRfileName
      self.imw.clear()
      try:
          imSize=self.tntData.shape[0]      #set image size to readout dimensions
          self.imw.tntData=np.swapaxes(self.tntData, 0,1)       #Usually the tnt data is readout, slice, phase encode, parmaeter, swap so that we have slice, RO, PE, Param
          self.imw.FoVX=1000*self.FoVro
          self.imw.FoVY=1000*self.FoVro
          self.imw.xscale=1000*self.FoVro/imSize
          self.imw.yscale=1000*self.FoVro/imSize
          self.imw.HorizontalLabel=self.TNMR.GradientOrientation[0]
          self.imw.VerticalLabel=self.TNMR.GradientOrientation[1]
          self.imw.HorizontalUnits='mm'
          self.imw.VerticalUnits='mm'
          if self.ui.cbProtocol.currentText()=="SCOUT":
              self.imw.processScout(nRF=-1)
          self.imw.show()
          try:
              self.imw.addPlotData(self.imw.tntData, shape=imSize)
          except:
              raise
      except:
          raise
          self.imw.show()
        
  def replotData(self):
      self.plotData(self.psPlotData)
      
  def plotData(self,data):
    '''plots NMR/MRI data vs index, time, freq,'''  
    self.psPlotData=data
    self.iStart=int(self.ui.leiStart.text())
    self.jStop=int(self.ui.lejStop.text())
    self.nSlice=self.psPlotData.shape[1]
    self.nPhase=self.psPlotData.shape[2]
    self.ui.sbPSDataSlice.setMaximum(self.psPlotData.shape[1]-1)
    self.ui.sbPSDataPhase.setMaximum(self.psPlotData.shape[2]-1)
    self.ui.sbPSDataParameter.setMaximum(self.psPlotData.shape[3]-1)
    self.dataMagPlot.clear()
    self.penstep=0
    dshape=data.shape
    npoints=dshape[0]
    self.tfid=np.arange(dshape[0]) * self.TNMR.DwellTime
    self.sfreq=-(np.fft.fftshift(np.fft.fftfreq(npoints, self.TNMR.DwellTime)))
    self.psFFTData=np.fft.fftshift(np.fft.fft(self.psPlotData, axis=0), axes=0)  
    nSlice=self.ui.sbPSDataSlice.value()
    nPhase=self.ui.sbPSDataPhase.value()
    nParam=self.ui.sbPSDataParameter.value()
    self.dataMagPlot.setTitle('Amplitude Slice={}, Phase step={}'.format(nSlice,nPhase)) 
    if self.ui.rbPSDataFID.isChecked():
        x=self.tfid
        self.dataXLabel="Time(s)"
    elif self.ui.rbPSDataSpectra.isChecked() and self.ui.rbPSDataFrequency.isChecked():
        x=self.sfreq
        self.dataXLabel="Frequency(Hz)"
    elif self.ui.rbPSDataSpectra.isChecked() and self.ui.rbPSDataPPM.isChecked():
        x=self.sfreq/self.tntfile.ob_freq[0]-self.ppmOffset     #convert to ppm with 
        self.dataXLabel="Frequency(ppm)"
    else:
        x=np.arange(npoints)
        self.dataXLabel="Index"
    # for j in range(self.nPhase):
    #     if j==nPhase or nPhase==-1:
    #       for i in range(self.nSlice):
    #         if i==nSlice or (nSlice==-1 and i<self.ncurveMax):
    p=pg.mkPen(pg.intColor(1), width=2)
    p1=pg.mkPen(pg.intColor(2), width=2)
    p2=pg.mkPen(pg.intColor(2), width=2)
    # p=pg.mkPen(pg.intColor(i+self.penstep), width=2)
    # p1=pg.mkPen(pg.intColor(i+self.penstep+1), width=2)
    # p2=pg.mkPen(pg.intColor(i+self.penstep+2), width=2)
    self.dataMagPlot.setLogMode(self.ui.cbPSDataLogX.isChecked(), self.ui.cbPSDataLogY.isChecked())
    if self.ui.rbPSDataFID.isChecked():
                  if self.ui.rbPSDataMagnitude.isChecked():
                      self.dataMagPlot.plot(x, np.absolute(self.psPlotData[:,nSlice,nPhase,nParam]), pen=p, width=2, name='FID Mag')   #plot mag
                  if self.ui.rbPSDataPhase.isChecked():
                      self.dataMagPlot.plot(x, np.angle(self.psPlotData[:,nSlice,nPhase,nParam]), pen=p, width=2, name='FID Phase')   #plot Phase
                  if self.ui.rbPSDataReal.isChecked():
                      self.dataMagPlot.plot(x, self.psPlotData[:,nSlice,nPhase,nParam].real, pen=p1, width=2, name='FID Real')   #plot real
                  if self.ui.rbPSDataImag.isChecked():
                      self.dataMagPlot.plot(x, self.psPlotData[:,nSlice,nPhase,nParam].imag, pen=p2, width=2, name='FID Imag')   #plot imag
    if self.ui.rbPSDataSpectra.isChecked():
                  if self.ui.rbPSDataMagnitude.isChecked():
                      self.dataMagPlot.plot(x, np.absolute(self.psFFTData[:,nSlice,nPhase,nParam]), pen=p, width=2, name='FFT Mag')   #plot Mag
                  if self.ui.rbPSDataPhase.isChecked():
                      self.dataMagPlot.plot(x, np.angle(self.psFFTData[:,nSlice,nPhase,nParam]), pen=p, width=2, name='FFT Phase')   #plot Phase
                  if self.ui.rbPSDataReal.isChecked():
                      self.dataMagPlot.plot(x, self.psFFTData[:,nSlice,nPhase,nParam].real, pen=p1, width=2, name='FFT Real')   #plot real
                  if self.ui.rbPSDataImag.isChecked():
                      self.dataMagPlot.plot(x, self.psFFTData[:,nSlice,nPhase,nParam].imag, pen=p1, width=2, name='FFT Imag')   #plot real
    self.dataMagPlot.setLabel('bottom',self.dataXLabel)
    self.dataMagPlot.setLabel('left', 'Signal')
    self.penstep+=10 
    self.addPSDataCrossHairs()
    #self.dataMagPlot.autoRange() 

  def autoRangePSdataPlot(self):
        self.dataMagPlot.autoRange() 
              
  def setPSDataPhase(self, phaseSpectra=0, firstSIndex=False):
    '''Set phase for all spectra default using first spectra and simplest algorythym find maximum signal phase to make real part maximum and imaginary zero'''
    marg=np.argmax(np.abs(self.psFFTData[:,phaseSpectra,0,0]))
    dphase=np.angle(self.psFFTData[marg,phaseSpectra,0,0])
    self.psPlotData=self.psPlotData*np.exp(-1j*dphase)
    y=np.fft.fftshift(np.fft.fft(self.psPlotData[:,phaseSpectra,0,0])).real
    maxVal=np.amax(y)   #find the maximum value, will select region around this maximum value to integrate
    maxInd=np.argmax(y)
    maxVal50 = 0.5*maxVal
    biggerCondition = [a > maxVal50 for a in y] #returns boolean array which is true for values above 50% of max value
    width=np.sum(biggerCondition)   #returns number of points above 50 max  ***Needs to be fixed if there are several large peaks***
    df=np.absolute(self.sfreq[1]-self.sfreq[0])
    self.FirstPeakFWHM=width*df
    self.currentF0=self.sfreq[maxInd]+self.TNMR.ObsFreq
    self.ui.leCurrentF0.setText("{:.6f}".format(self.currentF0/10**6))
    self.plotData(self.psPlotData)  #plot data
    self.ui.lePSDataFWHM.setText('{:.2f}'.format(self.FirstPeakFWHM))

  def plotF0PeakWidth(self):
    nPhase=self.ui.sbPSDataPhase.value()
    nParam=self.ui.sbPSDataParameter.value()
    nspectra=self.psFFTData.shape[1]
    self.F0PeakWidth=np.zeros((nspectra,2))
    df=np.absolute(self.sfreq[1]-self.sfreq[0])
    for slice in range(nspectra):
          spectra= self.psFFTData[:,slice,nPhase,nParam].real
          imax, fwhm= self.findF0PeakWidth(spectra)
          self.F0PeakWidth[slice,1]=fwhm*df
          self.F0PeakWidth[slice,0]=self.sfreq[imax]
          title=self.ui.leGradientOrientation.text()[0] +'-Gradient Ringdown Test'
    self.dataMagPlot.clear()
    self.dataMagPlot.addLegend()
    if self.ProtocolName=='FID90ECC':
        x=self.gradRingdownDelay
        self.dataMagPlot.setLabel('bottom', 'Ringdown Delay(s)')
        self.dataMagPlot.setLogMode(True, False)
    else:
        x=np.arange(nspectra)
        self.dataMagPlot.setLogMode(False, False)
        title='F0, FWHM'
    self.dataMagPlot.plot(x,self.F0PeakWidth[:,0], name='F0', symbol='x',symbolPen ='r')   #plot Mag
    self.dataMagPlot.plot(x,self.F0PeakWidth[:,1], name='fwhm', symbol='o',symbolPen ='b')   #plot Mag
    self.dataMagPlot.setLabel('left', 'Frequency(Hz)') 
    self.dataMagPlot.setTitle(title) 
    self.dataMagPlot.autoRange()
                           
  def addPSDataCrossHairs(self):
      self.infx1.setValue(0.0)
      self.infx2.setValue(0.0)
      self.infy1.setValue(0.0) 
      self.dataMagPlot.addItem(self.infx1)
      self.dataMagPlot.addItem(self.infx2)
      self.dataMagPlot.addItem(self.infy1)
     
  def hideCrossHairs(self):
      self.infy1.hide()
      self.infy2.hide()
 
  def showCrossHairs(self):
      self.infy1.show()

  def updatePSDataMarkers(self):
      if self.ui.rbPSDataSpectra.isChecked():
          mlabel='df(Hz)'
      else:
          mlabel='dt(ms)'
      self.ui.lePSDataPlotInfo.setText(mlabel+'={:6.3f}'.format((self.infx2.value()-self.infx1.value())))
            
  def sliceIndexChange(self):
      self.sliceIndex=self.ui.sbPSDataSlice.value()
      self.plotData(self.psPlotData) 
        
  def phaseIndexChange(self):
      self.phaseIndex=self.ui.sbPSDataPhase.value()
      self.plotData(self.psPlotData)
      
  def parameterIndexChange(self):
      self.parameterIndex=self.ui.sbPSDataParameter.value()
      self.plotData(self.psPlotData)
      
  def PSDataPhaseAdjust(self):
      phase=self.ui.hsPSDataPhaseAdjust.value() *np.pi/180
      data=self.tntData*np.exp(-1j*phase)
      self.plotData(data)  #plot data
                 
  def calculateBaselines(self):
      '''Calculates baselines assuming end of the FID/sprectra should be 0
      caclulates from self.blRegionStart to self.blRegionStart 
      Note Tecmag arbitrarily zeros the last 1% of the data as part of their filtering'''
      bstart=int(self.blRegionStart*self.data.real.shape[0])   #calculate baselines as the average of the data beyond self.blRegion
      bstop=int(self.blRegionStop*self.data.real.shape[0])   #calculate baselines as the average of the data beyond self.blRegion
      self.dataBaseline=np.zeros((self.data.real.shape[1],self.data.real.shape[2])) + 1j*np.zeros((self.data.imag.shape[1],self.data.imag.shape[2]))    #array of complex baseline values
      #smax=np.amax(np.absolute(self.data.real))
      for i in range(self.nSpectra):
        for j in range(self.nRepeats):
          self.dataBaseline[i,j]=np.average(self.data[bstart:bstop,i,j,0].real)+1j*np.average(self.data[bstart:bstop,i,j,0].imag)     # baseline is the averagrion value of last part of the data

      
  def subtractBaselines(self):
      self.calculateBaselines()
      for i in range(self.nSpectra):
        for j in range(self.nRepeats):
          self.data[:,i,j,0]=self.data[:,i,j,0]-self.dataBaseline[i,j]
          self.data[-self.TechMagEndZeros:,i,j,0]=0     #zero the last set of points on the  waverform since TechMag sets them to 0
      for j in range(self.nRepeats):
          self.message('<b>Subtract baselines:</b>'+np.array2string(self.dataBaseline[:,j], precision=2, separator=',',suppress_small=True))
      self.plotData() 

  def writeTNMRComment(self, write=True):
    ''' writes comment to TNMR, which likes /r/n to display correctly'''
    comment=''
    comment+='******Required Fields******\r\n'
    comment+= 'Protocol={}\r\n'.format(self.ProtocolName)
    comment+= 'SampleID={}\r\n'.format(self.ui.leSequenceID.text())
    comment+= 'SampleTemperature(C)={:6.2f}\r\n'.format(self.sampleTemperature)
    comment+= 'ImageOrientation={}\r\n'.format(self.ui.cbGradOrientation.currentText())
    comment+= 'GradientOrientation={}\r\n'.format(self.ui.leGradientOrientation.text())
    comment+= 'FoV(mm)={:6.2f}\r\n'.format(self.FoVro*1000)
    comment+= 'SliceThickness(mm)={:6.2f}\r\n'.format(self.ui.dspboxSliceThickness.value())
    comment+= 'SliceSpacing(mm)={:6.2f}\r\n'.format(self.ui.dspboxSliceSpacing.value())
    comment+= 'sliceArrayCenter(mm)={:6.2f}\r\n'.format(self.sliceArrayCenter*1000)
    comment+= 'RunTime={}\r\n'.format(self.ui.leExpectedAcqTime.text())
    if self.setupdict['Bvalue']:
        comment+= 'b-Values(s/mm^2)={}\r\n'.format(np.array2string(self.bValueArray, precision=2, separator=',',suppress_small=True))
    comment+='******Optional comments******\r\n'
    comment+='Type Stuff Here\r\n'
 #         comment+= 'SliceThickness(mm){:6.2f}\n'.format(self.protocolaName)
    if write:
        self.TNMR.setComment(comment, append=False)
    self.ui.txtTNMRComment.clear()
    self.ui.txtTNMRComment.setText(comment)

#***********Opsens Temperature      
  def readOpsensTemp(self):
    '''read Opsens FIber Optic THermometer, has problems since EOT characters not stripped properly'''
    try:
        self.Opsens.write('Channel1:DATA? 1')  #'CH1:DATA
        a=self.Opsens.read()
        b=self.Opsens.read()
        self.OpsensTemp=float(b)
        #self.OpsensTempArray=np.append(self.OpsensTempArray,self.OpsensTemp)
    except:
        self.OpsensTemp=np.nan
    return self.OpsensTemp


#***PloyScience chiller************
  def turnOffPolySci(self):
    PSOffOn = self.PS.query('SO0')
    self.ui.pbChillerOn.setStyleSheet("background-color: rgb(240, 240, 240)")
    return PSOffOn 
  def turnOnPolySci(self):
    PSOffOn = self.PS.query('SO1')
    self.ui.pbChillerOn.setStyleSheet("background-color: rgb(100, 255, 100)")
    return PSOffOn 

  def readPSTemp(self):
    try:
        self.PSTemp = float(self.PS.query('RT'))
    except:
        self.PSTemp=np.NaN
    #self.PSTempArray=np.append(self.PSTempArray,self.PSTemp)
    return self.PSTemp

  def readPSsetpoint(self):
    try:
        psSP=self.PS.query('RS')
        self.PSsetpoint = float(psSP)
        return self.PSsetpoint
    except:
        #print('PolyScience setpoint not read:')
        return np.nan
    #self.PSsetPointArray=np.append(self.PSsetPointArray,self.PSsetpoint)
    

  def setPSsetpoint(self, tsp=False):
    '''Set Polyscience Chiller temperature setpoint'''
    if tsp==False:
        tsp, ok = QInputDialog().getDouble(self, "PolyScience Setpoint","(C)", self.Tsp, 0, 70)
        if ok :
            self.Tsp=tsp
        else:
            return
    else:
        self.Tsp=tsp
    if self.Tsp>self.ChillerMinT and self.Tsp<self.ChillerMaxT:
        self.PS.query('SS' +'{:06.2f}'.format(self.Tsp))
        self.temperatureSlope=5E-3  #set the temperate slope high anticipating a temperature change
    else:
        self.message('Chiller temperature not changed: Setpoint must be between {:03.1f}C and {:03.1f}C'.format(self.ChillerMinT,self.ChillerMaxT))

  def calculateDesiredChillerSetPoint(self):
      '''Calculates desired chiller setpoint given the desired sample temperature and the current measured temperature'''
      Terror=(self.opsensTemperatureAv-self.ui.dspboxDesiredSampleTemp.value())*self.TcontrolErrorGain
      if np.absolute(Terror)>5: #limit setpoint overshoot to no more than 5C
          Terror=5*np.sign(Terror)
      desiredSetPointTemperature=self.ui.dspboxDesiredSampleTemp.value()-Terror
      return desiredSetPointTemperature
      
  def setTemperature(self, temperature=20.0, waitUntilStable=False, temperatureStableRange=1):
      toffset=self.ChillerOffsetSlope*(temperature-self.ChillerOffsetTemperature)
      tsp=temperature+toffset
      self.setPSsetpoint(tsp)
      self.message('Chiller temperature set to {:03.1f}C'.format(tsp))
      self.temperatureStableRange=temperatureStableRange
      self.desiredTemperature = temperature
      self.ui.dspboxDesiredSampleTemp.setValue(self.desiredTemperature)
      if waitUntilStable:
          self.message('Waiting for Temperature Stable') 
          while not self.checkTemperatureStable():      #If the temperature is not stable then wait but process events in the mean time
              app.processEvents()
          self.message('Waiting for Temperature Stable', color='green', bold=True)    
      
  def checkTemperatureStable(self):
      '''Returns true if the current temperature is close to the desired temperature and the temperature is not changing much, False otherwise'''
      if np.absolute((self.opsensTemperature-self.desiredTemperature))<self.temperatureStableRange and  np.absolute(self.temperatureSlope)<self.temperatureStableSlope:
          self.temperatureStable=True
          return True
      else: 
          self.temperatureStable=False
          return False
      
  def rAv(self, current, new, alpha=0.01):
      '''Returns running average of a parmameter given its current value and its new reading with weighting factor alpha'''
      return (1-alpha)*current+alpha*new
#***************Helper routines**************************
  def findF0PeakWidth(self, y):
        '''finds FWHM of array y that has 1 simple peak, need to upgrade to SciPy peak width'''
        maxVal=np.amax(y)   #find the maximum value, will select region around this maximum value to integrate
        maxInd=np.argmax(y)
        maxVal50 = 0.5*maxVal
        biggerCondition = [a > maxVal50 for a in y] #returns boolean array which is true for values above 50% of max value
        width=np.sum(biggerCondition)+1   #returns number of points above 50 max  ***Needs to be fixed if there are several large peaks***
        F0=maxInd
        return F0, width
  
  def pause(self,t):
    '''pause in seconds, but will do events while waiting'''
    if t<10:
        nsteps=10
    else:
        nsteps=100
    for i in range(nsteps):
        app.processEvents()
        if self.recipeAbort:
            return
        time.sleep(t/nsteps)
        
  def get_sec(self,time_str):
    """Get seconds from time."""
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)
  
  def message(self, m, ctime=False, report=True, color='black', bold=False): 
    '''prints message in gui message box'''
    '''Report=True indicates that message is to be included in output report'''
    #self.ui.txtMessages.setLineWrapMode(1)
    m= self.formatText(m, color=color, bold=bold)
    if ctime== True:
        self.ui.txtMessages.append(time.strftime("%c") + ': ' + m)
    else:
        self.ui.txtMessages.append(m)

  def formatText(self, s, color='black', bold=False):
    s='<font color=' +color + '>' + s + '</font>'
    if bold:
      s='<b>' + s + '</b>'
    return  s  #returns string with color font bold etc

  # def writeScreenSaverTextReg(self,text, id=''):
  #         self.NMRControlWriteKey = OpenKey(self.registry,'SOFTWARE\\VB and VBA Program Settings\\NMRControl\\EXT_WRITE',0, KEY_ALL_ACCESS)
  #         SetValueEx(self.NMRControlWriteKey, 'WRITE_VALUES', 0,REG_SZ, sout)
  #         SetValueEx(self.NMRControlWriteKey, 'DO_WRITE',0, REG_SZ, 'TRUE')
  #         CloseKey(self.NMRControlWriteKey)
  #         self.message('registry write: '+id)
                         
  def closeEvent(self,event):
    self.closePicoscope()
    #print ('Closing pyMRI', event)
    
class fRectROI(pg.RectROI):
    """Defines a rectangular ROI using pyqtgraph's RectROI"""
    def __init__(self, callingform, pos, size, label,   **args):   
        pg.ROI.__init__(self, pos, size, **args)
        self.aspectLocked = False
        self.pyMRIform=callingform
        self.Index = 0
        self.label = pg.TextItem(label, callingform.lblColor, anchor = (0,0))
        self.label.setPos(pos[0],pos[1])
        #self.label.setFont(callingform.lblFont)
                
class plotWindow(QMainWindow):
      def __init__(self,parWin, image=None, parent=None):
            '''Defines window for plotting and analyzing data, fit to data, residuals'''    
            super(QMainWindow, self).__init__()
            self.win=self   #QMainWindow()
            self.dplot = pg.PlotWidget()
            self.plotName=''
            self.win.setCentralWidget(self.dplot)
            self.win.resize(800,600)
            self.win.setWindowTitle('Recipe Data')
            self.parWin=parWin      #parent window
            self.menu = self.win.menuBar()
            self.penr = QPen(Qt.red, 0.5)
            self.penw = QPen(Qt.white, 0.5)
            self.peny = QPen(Qt.yellow, 0.5)
            self.symbolpen=None
            self.penb = pg.mkPen(color='b',width=2)
            self.bblabelStyle = {'color':'w', 'font-size': '18px'}
            self.bbtitleStyle = {'color':'w', 'font-size': '18px'}
            self.wblabelStyle = {'color':'k', 'font-size': '18px'}
            self.wbtitleStyle = {'color':'k', 'font-size': '18px'}
            self.labelStyle=self.bblabelStyle
            self.titleStyle=self.wbtitleStyle
            self.symbolSize=12
            self.logX=False
            self.logY=False
            self.bPlotAll=True       #flag to determine whether to plot all curves or just a selected one.
            self.bClearData=True     #flag to determine whether to clear old data before plotting new data
            self.plotTitle=''
            self.dplot.showAxis('right')
            self.dplot.showAxis('top')
            self.dplot.setLabel('bottom','Time(s)', **self.labelStyle)
            self.dplot.setLabel('left',"Signal", **self.labelStyle)
            self.dplot.plotItem.getAxis('left').setPen(self.penw)
            self.dplot.plotItem.getAxis('bottom').setPen(self.penw)
            self.symb=['o', 's', 'd', 't', 't1', 't2','t3', 'p','+', 'h', 'star','x']
            self.plotType=0 #default plot second array column = temperature
            self.data=np.zeros((1,10))
            self.nColors=7
            self.colors= ['w', 'r', 'g', 'b', 'c', 'm', 'y']
            self.fileMenu = self.menu.addMenu('&File')    
            self.actionSaveData = QAction('Save data', self.win)
            self.fileMenu.addAction(self.actionSaveData)
            self.actionSaveData.triggered.connect(self.saveData)
            self.actionReadData = QAction('Read data', self.win)
            self.fileMenu.addAction(self.actionReadData)
            self.actionReadData.triggered.connect(self.readData)
            self.actionExit = QAction('Exit', self.win)
            self.fileMenu.addAction(self.actionExit)
            self.actionExit.triggered.connect(self.exitPlot)
            #
            self.plotMenu = self.menu.addMenu('&Plot')
            self.actionPlotTemperatureData = QAction('Plot Temperature', self.win)
            self.plotMenu.addAction(self.actionPlotTemperatureData)
            self.actionPlotTemperatureData.triggered.connect(self.plotTemperatures)
            
            self.actionTstable = QAction('Plot Temperature Stable', self.win)
            self.plotMenu.addAction(self.actionTstable)
            self.actionTstable.triggered.connect(self.plotTStable)
            
            self.actionTNMRactive = QAction('Plot TNMR active', self.win)
            self.plotMenu.addAction(self.actionTNMRactive)
            self.actionTNMRactive.triggered.connect(self.plotTNMRactive)
            
            self.actionchangeBackgroundColor = QAction('Change background color', self.win)
            self.plotMenu.addAction(self.actionchangeBackgroundColor)
            self.actionchangeBackgroundColor.triggered.connect(self.changeBackground)
            
#             self.actionTsvsTrtd = QAction('Plot sample temperature vs RTD temperature', self.win)
#             self.plotMenu.addAction(self.actionTsvsTrtd)
#             self.actionTsvsTrtd.triggered.connect(self.plotTsvsTrtd)
            
            self.actionTsTrtdvsTime = QAction('Plot Fiber Optic temperature and RTD temperature vs Time', self.win)
            self.plotMenu.addAction(self.actionTsTrtdvsTime)
            self.actionTsTrtdvsTime.triggered.connect(self.plotTsTrtdvsTime)
            
            self.actionTrtdvsTop = QAction('Plot sample RTD temperature vs Opsens temperature', self.win)
            self.plotMenu.addAction(self.actionTrtdvsTop)
            self.actionTrtdvsTop.triggered.connect(self.plotTrtdvsTop)
            
            self.analysisMenu = self.menu.addMenu('&Analysis')    

            self.actionClearPlot = QAction('Clear Data', self.win)
            self.plotMenu.addAction(self.actionClearPlot)
            self.actionClearPlot.triggered.connect(self.clearPlot)
            #try: 
            self.inf1 = pg.InfiniteLine(movable=True, angle=90, label='x={value:0.4e}', 
                       labelOpts={'position':0.1, 'color': (200,200,100), 'fill': (200,200,200,50), 'movable': True})
            self.inf2 = pg.InfiniteLine(movable=True, angle=0, pen=(0, 0, 200),  hoverPen=(0,200,0), label='y={value:0.4e}', 
                       labelOpts={'color': (200,0,0), 'movable': True, 'fill': (0, 0, 200, 100)})
            
      def clearPlot(self):
          '''will cause the arrays to be cleared and array monitoring restarted'''
          self.dplot.clear()
          self.parWin.nUpdates=1        
      
      def addCrossHairs(self):
          self.dplot.addItem(self.inf1)
          self.dplot.addItem(self.inf2)
            
      def plotTemperatures(self):
        self.plotType=0
        self.dplot.plotItem.getAxis('left').setPen(self.penw)        
        self.dplot.setLabel('left', 'Temperature(C)', **self.labelStyle)
        self.plotData(self.data)
      def plotTPolyScience(self):
        self.plotType=2
        self.dplot.plotItem.getAxis('left').setPen(self.penw)        
        self.dplot.setLabel('left', 'Temperature(C)', **self.labelStyle)
        self.plotData(self.data)           
          
      def plotTStable(self):
          self.plotType=5
          self.dplot.plotItem.getAxis('left').setPen(self.penw)   
          self.dplot.setLabel('left', 'Tstable Flag', **self.labelStyle)
          self.plotData(self.data)
           
      def plotTNMRactive(self):
          self.plotType=6
          self.dplot.plotItem.getAxis('left').setPen(self.penw)   
          self.dplot.setLabel('left', 'TNMR Active Flag',**self.labelStyle)
          self.plotData(self.data)
          
#       def plotTsvsTrtd(self):
#           self.plotType=7
#           self.dplot.plotItem.getAxis('left').setPen(self.penw)   
#           self.dplot.setLabel('left', 'Sample Temperature',**self.labelStyle)
#           self.dplot.setLabel('bottom', 'RTD Temerature',**self.labelStyle)
      def plotTsTrtdvsTime(self):
          self.plotType=7
          self.dplot.plotItem.getAxis('left').setPen(self.penw)   
          self.dplot.setLabel('left', 'Sample Temperature and RTD Temperature',**self.labelStyle)
          
      def plotTrtdvsTop(self):
          self.plotType=8
          self.dplot.plotItem.getAxis('left').setPen(self.penw)   
          self.dplot.setLabel('left', 'RTD Temperature',**self.labelStyle)
          self.dplot.setLabel('bottom', 'FiberOptic Temperature',**self.labelStyle)
                                              
      def plotData(self, data):
        self.data=data
        self.dplot.plotItem.getAxis('left').setPen(self.penw)
        self.dplot.plotItem.getAxis('bottom').setPen(self.penw)
        if self.plotType==0:
            self.dplot.plot(data[:,0],data[:,2], clear=True, pen=self.penb, symbol='o',symbolSize=10, symbolPen =self.symbolpen, symbolBrush =[pg.mkBrush(self.colors[int(v % self.nColors)]) for v in data[:,1]])
            self.dplot.plot(data[:,0],data[:,3], clear=False, pen=self.penb, symbol='s',symbolSize=10, symbolPen =self.symbolpen, symbolBrush =[pg.mkBrush(self.colors[int(v % self.nColors)]) for v in data[:,1]])
            self.dplot.plot(data[:,0],data[:,4], clear=False, pen=self.penb, symbol='d',symbolSize=10, symbolPen =self.symbolpen, symbolBrush =[pg.mkBrush(self.colors[int(v % self.nColors)]) for v in data[:,1]])
        else:
            self.dplot.plot(data[:,0],data[:,self.plotType], clear=True, pen=self.penb, symbol='o',symbolSize=10, symbolPen =self.symbolpen, symbolBrush =[pg.mkBrush(self.colors[int(v % self.nColors)]) for v in data[:,1]])
 

      def saveData(self, file=None):
          if file==None:
              f = QFileDialog.getSaveFileName(parent=None, caption="Recipe Data File Name",filter="*.dat")
              if f[0]=='':
                  return 'cancel'
              else:
                  self.dataFileName=str(f[0])+'.dat'
          else:
              ft=time.strftime("_%Y%m%d_%H_%M")
              self.dataFileName=file.strip('.rcp.')+ft + '.dat'
          try:
              np.savetxt(self.dataFileName, self.data, header=self.parWin.dataHeader, fmt='%8.2f')
              self.parWin.message('Data file save as: ' + self.dataFileName)
          except:
              self.parWin.message('Data file cannot be saved: ' + self.dataFileName)

      def readData(self):
          f = QFileDialog.getOpenFileName(parent=None, caption="Recipe File Name",filter="*.dat")
          if f[0]=='':
              return 'cancel'
          else:
              self.dataFileName=str(f[0])
          self.plotData(np.loadtxt(self.dataFileName))

               
      def integrateData(self):
        data=self.dplot.getData()

      def changeBackground(self):
            col = QColorDialog.getColor()
            self.dplot.setBackground(background=col) 
                    
      def exitPlot(self):
          exit()
#Useful for debugging Qt applications where the app closes without giving error message
sys._excepthook = sys.excepthook 
def exception_hook(exctype, value, traceback):
    print("Missed Exception:", exctype, value, traceback)
    if str(exctype).find('pyvisa.errors.VisaIOError')!=-1:
        QMessageBox.warning(None,'PyVisa Error', 'Close applications using TNMR, Opsens, PolyScience')
    sys._excepthook(exctype, value, traceback) 
    sys.exit(1) 
#*******
sys.excepthook = exception_hook       
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setStyleSheet("QWidget{font-size: 8pt;}") 
    main = MRIcontrol()
    main.show()
    sys.exit(app.exec_())