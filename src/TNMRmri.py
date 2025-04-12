'''
Created on Feb 12, 2022
Class to drive TNMR console, optimized for Agilent preclinical MRI

@author: stephen russek
'''

import sys
import win32com.client # if not exist, install via "pip install pywin32"
import numpy as np
#gradient orientaiton is GrGpGs
#scanOrientation={ 'XYZ' : 'Axial RO=X, PE=Y' , 'YXZ' : 'Axial RO=Y, PE=X', 'XZY' : 'Coronal RO=X, PE=Z', 'ZXY' : 'Coronal RO=Z, PE=X', 'ZYX' : 'Sagittal RO=Z, PE=Y', 'YZX' : 'Sagittal RO=Y, PE=Z'}
scanOrientation={'XZY':'Coronal RO=X, PE=Z','ZXY':'Coronal RO=Z, PE=X',\
                                      'ZYX':"Sagittal RO=Z, PE=Y", 'YZX':'Sagittal RO=Y, PE=Z',\
                                      'XYZ':'Axial RO=X, PE=Y', 'YXZ':'Axial RO=Y, PE=X',\
                                      'Coronal RO=X, PE=Z':'XZY', 'Coronal RO=Z, PE=X':'ZXY',\
                                      "Sagittal RO=Z, PE=Y":'ZYX', 'Sagittal RO=Y, PE=Z':'YZX',\
                                      'Axial RO=X, PE=Y':'XYZ', 'Axial RO=Y, PE=X':'YXZ'}

class TNMR ():
  ''' Opens and communicates with tNMR console'''
  def __init__(self , rm, parent = None):
    self.defTNMRFile = r" C:\TNMR\data\microMRI\single_FID_MWOff.tnt"
    self.App = win32com.client.Dispatch('NTNMR.Application')
    self.psTableList=''     #pulse sequence table list
    #******B0 compensation and Gradient PreEmphasis
    self.gradientMode='Low'
    self.A0xLowGrad=  30.699        #multiplier values to give 100mT/m when gradient amplitude is set to 100
    self.A0yLowGrad=  30.564
    self.A0zLowGrad=   32.729
    if self.gradientMode=='Low':
        self.A0x=  self.A0xLowGrad        #multiplier values to give 100mT/m when gradient amplitude is set to 100
        self.A0y=  self.A0yLowGrad
        self.A0z=  self.A0zLowGrad
    #default values for B0 comp and GRad. Preemph.    
    self.B0CompValuesDefault={'DC.bx':0, 'A0.bx':0, 'A1.bx':0,'A2.bx':0,'A3.bx':0,'A4.bx':0, 'A5.bx':0,'T1.bx':0.0002,'T2.bx':0.002,'T3.bx':0.02,'T4.bx':0.2,'T5.bx':2,\
                       'DC.by':0, 'A0.by':0, 'A1.by':0,'A2.by':0,'A3.by':0,'A4.by':0, 'A5.by':0,'T1.by':0.0002,'T2.by':0.002,'T3.by':0.02,'T4.by':0.2,'T5.by':2,\
                       'DC.bz':0, 'A0.bz':0, 'A1.bz':0,'A2.bz':0,'A3.bz':0,'A4.bz':0, 'A5.bz':0,'T1.bz':0.0002,'T2.bz':0.002,'T3.bz':0.02,'T4.bz':0.2,'T5.bz':2}
    self.gradPreEmphasisValuesDefault={'DC.x':0, 'A0.x':self.A0x, 'A1.x':0,'A2.x':0,'A3.x':0,'A4.x':0, 'A5.x':0,'T1.x':0.0002,'T2.x':0.002,'T3.x':0.02,'T4.x':0.2,'T5.x':2,\
                       'DC.y':0, 'A0.y':self.A0y, 'A1.y':0,'A2.y':0,'A3.y':0,'A4.y':0, 'A5.y':0,'T1.y':0.0002,'T2.y':0.002,'T3.y':0.02,'T4.y':0.2,'T5.y':2,\
                       'DC.z':0, 'A0.z':self.A0z, 'A1.z':0,'A2.z':0,'A3.z':0,'A4.z':0, 'A5.z':0,'T1.z':0.0002,'T2.z':0.002,'T3.z':0.02,'T4.z':0.2,'T5.z':2}  
    #current values for B0 comp and GRad. Preemph.
    self.B0CompValues=self.B0CompValuesDefault.copy()
    self.gradPreEmphasisValues=self.gradPreEmphasisValuesDefault.copy()
     
         
  def openConsole(self):
      '''opens TNMR console'''
      self.App = win32com.client.Dispatch('NTNMR.Application')
#      self.openFile(self.defTNMRFile)
      
  def zg(self):
      '''zero and go starts NMR scan'''
      self.currentFile.ZG()
      
  def stop(self):
      '''stops after phase cycle completes'''
      self.currentFile.Stop()
      
  def abort(self):
      '''Aborts immediately'''
      self.currentFile.Abort
            
  def rs(self):
      '''zero and go starts NMR scan'''
      self.currentFile.RG()
      
  def saveCurrentFile(self, filename=''):
      '''saves current file, if no filename is provided saves as filename+date'''
      self.currentFile.SaveAs(filename)
 

  def saveShims(self, filename=''):
      '''saves current file, if no filename is provided saves as filename+date'''
      if not hasattr(self, 'App'):
          self.App = win32com.client.Dispatch('NTNMR.Application')
      self.App.SaveShims()
                  
  def openFile(self, filename):
        self.currentFileName=filename
        try:
            self.currentFile = win32com.client.GetObject(filename) # the dataset opens in TNMR
            #self.App = win32com.client.Dispatch('NTNMR.Application')
            self.getPSparams()
            return True
        except:
            print('Cannot open tnt file')
            return False
        
  def closeActiveFile(self):
      '''close current file'''
      self.App.CloseActiveFile==True
                    
  def getPSparams(self):
        #Standard parameters that are always present, all are input as strings and converted to integer or floats where necessarY     
        self.xCurPos = self.currentFile.GetCursorPosition
        self.ObsFreq = self.getTNMRfloat("Observe Freq.")*10**6       #Observe frequency comes in as a float, not a string, stored in Hz, displayed in MHz
        self.nAcqPoints = int(self.currentFile.GetNMRParameter("Acq. Points"))
        self.SW = self.getTNMRfloat("SW +/-")
        self.ReceiverGain = int(self.getTNMRfloat("Receiver Gain"))
        self.finishTime=self.currentFile.GetNMRParameter('Exp. Finish Time')
        self.Scans1D = int(self.currentFile.GetNMRParameter("Scans 1D"))
        self.Points2D = int(self.currentFile.GetNMRParameter("Points 2D"))
        self.Points3D = int(self.currentFile.GetNMRParameter("Points 3D"))
        self.Points4D = int(self.currentFile.GetNMRParameter("Points 4D"))
        self.ActualScans1D = int(self.currentFile.GetNMRParameter("Actual Scans 1D"))
        self.ActualPoints2D = int(self.currentFile.GetNMRParameter("Actual Points 2D"))
        self.ActualPoints3D = int(self.currentFile.GetNMRParameter("Actual Points 3D"))
        self.ActualPoints4D = int(self.currentFile.GetNMRParameter("Actual Points 4D"))
        self.DwellTime = self.getTNMRparam("Dwell Time")
        self.LastDelay = self.getTNMRparam("Last Delay")
        self.AcqTime = self.getTNMRparam("Acq. Time") 
        self.SADimension = int(self.currentFile.GetNMRParameter("S.A. Dimension"))
        self.expectedAcqTime =self.currentFile.GetNMRParameter("Exp. Elapsed Time")
        self.sequenceTime = self.currentFile.GetSequenceTime #sequence time in s
        self.acqDate = self.currentFile.GetNMRParameter("Date")
        self.PSTableList=self.currentFile.GetTableList      #get list of tables in the pulse sequence
        if self.PSTableList.find("GpAmpTbl") !=-1:
            self.phaseEncodeArray=self.currentFile.GetTable("GpAmpTbl")  #Tables are  comma or space delineated strings
        self.GradientOrientation = self.currentFile.GetNMRParameter("Grd. Orientation") #string 'XYZ'
        #self.tntArrayShape=self.getTNMRparam('actual_npts')
        #pulse sequence specific floating point parameters that may or may not be there
        self.currentShimUnits=self.getTNMRfloat('Shim Units')              
        self.RFpw = self.getTNMRfloat("pw")     #RF excite pulse width
        self.RFpw180 = self.getTNMRfloat("pw180")     #RF excite pulse width
        self.rfAttn90 = self.getTNMRfloat("rfAttn90")       #RF attenuation for 90 degree pulse
        self.rfAttn180 = self.getTNMRfloat("rfAttn180")
        self.GspoilDAC = self.getTNMRfloat("Gspoil")    #End of excitation spoiler gradient DAC value
        self.tspoil = self.getTNMRfloat("tspoil")    #End of excitation spoiler length 
        self.GdpDAC = self.getTNMRfloat("Gdp")      #phase gradient crusher
        self.tcrush = self.getTNMRfloat("tcrush")    #crusher gradient duration        
        self.GpDAC = self.getTNMRfloat("Gp")        #phase gradient
        self.GrDAC = self.getTNMRfloat("Gr")        #readout gradient
        self.GrrDAC = self.getTNMRfloat("Grr")      #REadout gradient rewind
        self.GsDAC = self.getTNMRfloat("Gs")        #slice gradient 
        self.GsrDAC = self.getTNMRfloat("Gsr") 
        self.tpe = self.getTNMRfloat("tpe")        #phase gradient pulse duration
        self.tramp = self.getTNMRfloat("tramp")        #gradient ramp time
        self.ti0= self.getTNMRfloat("ti0")        #Inversion time when tiDelay =0
        self.tr0 = self.getTNMRfloat("tr0")        #repetition time when final delay=0
        self.te0 = self.getTNMRfloat("te0")        #Echo time when teDelay =0
        for key in self.B0CompValues:       #download B0 compensation parameters
            self.B0CompValues[key]=np.round(self.getTNMRparam(key),6)
        for key in self.gradPreEmphasisValues:  #download gradient preEMphasis parameters
            self.gradPreEmphasisValues[key]=np.round(self.getTNMRparam(key),6)

                    
  def setPSparams(self):
        '''sets pulse sequence parameters in TNMR''' 
      #*****Parameters that should always be there*************    
        self.currentFile.SetNMRParameter("Observe Freq.", '{:.6f}MHz'.format(self.ObsFreq/10**6))
        self.currentFile.SetNMRParameter("Acq. Points", self.nAcqPoints)
        self.currentFile.SetNMRParameter("Receiver Gain",'{}'.format(self.ReceiverGain))
        self.currentFile.SetNMRParameter("Scans 1D",self.Scans1D)
        self.currentFile.SetNMRParameter("Points 2D", self.Points2D)
        self.currentFile.SetNMRParameter("Points 3D", self.Points3D)
        self.currentFile.SetNMRParameter("Points 4D", self.Points4D)
        self.currentFile.SetNMRParameter("Dwell Time",'{:6.4f}m'.format(self.DwellTime*1000))
        self.currentFile.SetNMRParameter("Last Delay", '{:8.3f}m'.format(self.LastDelay*1000))
        self.currentFile.SetNMRParameter("Grd. Orientation",self.GradientOrientation) #string 'XYZ'
    #*****Parameters that may be there*************   
        self.PSTableList=self.currentFile.GetTableList      #get list of tables in the pulse sequence
        if self.PSTableList.find("GpAmpTbl") !=-1:
            self.currentFile.SetTable("GpAmpTbl", self.phaseEncodeArray)         
        try:
            self.currentFile.SetNMRParameter("pw", '{:5.1f}m'.format(self.RFpw*1000))       #note RF90 is  a float in seconds, convert to a string in ms with m 
        except:
            print ("Cannot set RFpw pulsewidth pw=")
        try:
            self.currentFile.SetNMRParameter("pw180", '{:5.1f}m'.format(self.RFpw180*1000))
        except:
            print ("Cannot set RFpw180 pulsewidth")
        try:
            self.currentFile.SetNMRParameter("rfAttn90", '{:5.1f}'.format(self.rfAttn90))
        except:
            print ('Cannot set rfAttn90')
        try:
            self.currentFile.SetNMRParameter("rfAttn180", '{:5.1f}'.format(self.rfAttn180))
        except:
            print ('Cannot set rfAttn180=', self.rfAttn180)

        try:
            self.currentFile.SetNMRParameter("Gspoil", '{:8.4f}'.format(self.GspoilDAC))
        except:
            pass
        try:
            self.currentFile.SetNMRParameter("Gdp", '{:8.4f}'.format(self.dGpDAC))      #Gradient crushers
        except:
            pass
        try:
            self.currentFile.SetNMRParameter("Gp", '{:8.4f}'.format(self.GpDAC))
            self.currentFile.SetNMRParameter("Gr", '{:8.4f}'.format(self.GrDAC))
            self.currentFile.SetNMRParameter("Grr", '{:8.4f}'.format(self.GrrDAC))
            self.currentFile.SetNMRParameter("Gs", '{:8.4f}'.format(self.GsDAC)) 
            self.currentFile.SetNMRParameter("Gsr", '{:8.4f}'.format(self.GsrDAC))
        except:
            pass
            #print('Cannot update slice, readout, and phase gradient parameters')   
              
        
  def getTNMRfloat(self, pname):
      '''get parameter and return as a float, float() will handle 'x.xm' strings and have the correct multiplier but not xm strings''' 
      try:
          return(float(self.currentFile.GetNMRParameter(pname)))
      except:
          return (self.getTNMRparam(pname))
        
  def getTNMRparam(self, pname):
      '''inputs a parameter string and outputs a float adjusting for unit marker'''  
      try:
          p=self.currentFile.GetNMRParameter(pname)     #get string parameter from dash board, replace multiplier and make floats
          if p.find('MHz') != -1:
              val=p.replace('MHz','')
              val=float(val)*1E6
              return(val)
              
          if p.find('Hz') != -1:
              val=p.replace('Hz','')
              val=float(val)
              return(val)
              
          if p.find('s') != -1:
              val=p.replace('s','')
              val=float(val)
              return(val)
                            
          if p.find('m') != -1:
              val=p.replace('m','')
              val=float(val)*1E-3
              return(val)
              
          if p.find('u') != -1:
              val=p.replace('u','')
              val=float(val)*1E-6
              return(val)
          return(float(p))
      except: 
          return (np.nan) 
                   
  def checkAcquisition(self):
      '''self.App.CheckAcquisition returns False when busy, True when finished
      This routine returns the negation:  True when busy or False when the system is idle or there is not current data file'''
      return not self.App.CheckAcquisition

  def getCurrentPSparams(self):
      self.finishTime=self.currentFile.GetNMRParameter('Exp. Finish Time')   
      
  def getScanOrientation(self,go):
      return scanOrientation[go]
  
  def compilePS(self):
      self.currentFile.Compile()   
               
  def setComment(self,comment, append=True):
      #oldcomment=self.currentFile.GetComment
      if append==True:
          oldcomment=self.currentFile.GetComment
          comment=oldcomment+": "+comment
      try:
          self.currentFile.SetComment(comment)
      except:
          print('Cannot load comment into TNMR')
      #self.App.SetComment(comment)
      self.comment=comment
  
  def setB0CompGradPreEmphToDefault(self):
      '''Sets B0Comp and Gradient PreEmphasis values back to default'''
      for key in self.B0CompValuesDefault.keys():
          if key.find('T')==-1:
            self.currentFile.SetNMRParameter(key, '{:8.4f}'.format(self.B0CompValuesDefault[key]))
          else:             
            self.currentFile.SetNMRParameter(key, '{:6.4f}m'.format(self.B0CompValuesDefault[key]*1000))       #if parameter is a time constant convert to ms and add an m
 
      for key in self.gradPreEmphasisValuesDefault.keys():
          if key.find('T')==-1:
              if key.find('DC')==-1:        #doi not zero DC.x, DC.y, DC.z  these are shim settings
                  self.currentFile.SetNMRParameter(key, '{:8.4f}'.format(self.gradPreEmphasisValuesDefault[key])) 
          else:    
            self.currentFile.SetNMRParameter(key, '{:6.4f}m'.format(self.gradPreEmphasisValuesDefault[key]*1000))       #if parameter is a time constant convert to ms and add an m
          
      for key in self.B0CompValues:       #download B0 compensation parameters
            self.B0CompValues[key]=np.round(self.getTNMRparam(key),6)
      for key in self.gradPreEmphasisValues:  #download gradient preEMphasis parameters
            self.gradPreEmphasisValues[key]=np.round(self.getTNMRparam(key),6)
               
