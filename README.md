# pyMRIControl
Python code that wraps Tecmag NMR/MRI console. Meant as a metrology MRI controllers with scopes, temperature control etc.

''' Created on Nov. 7, 2023 Class to control TechMag MRI system along with associated controls including temperature, picoscope, interlocks etc Meant to control a Metrology MRI where complex raw data is always stored and retained Raw k-space data is stored in 4D numpy arrays of complex floats, scope and environmental data are also obtained and stored THe GUIS are written in pyqt, and graphsincs use pyqtgraph

#required packages

Anaconda 3 with Python 3.7 (64 bit, Python, PyQT5, Numpy, Scipy, Pillow )
pyqtgraph Version: 0.10.0 (for plotting and image windows)
***To Do #" src\pyuic5.bat src\MRIcontrol.ui -o src\MRIcontrolGui.py " from system shell to regenerate command input window #" src\pyuic5MRLab.bat src\MRIcontrol.ui -o src\MRIcontrolGui.py " from system shell to regenerate command input window
@author: stephen russek

Important Conventions: All parameters are stored in SI units m,s,Tesla,°C,A, V; however display values can be in convenience units mm, ms, ...****

Program loads a .tnt file, modifies it, runs it or puts it into a queue/recipe Safety limits on the RF and gradient strength are embedded in the .tnt file Pulse sequence files must contain standard parameters and tables to allow the pulse sequence to be recognized and modified.

To add a protocol, 1. write basic TNMR sequence, 2. save in StandardSequenceDirectory with filename=desired protocol name, 3. add protocolName to self.protocolList, 4. make a setup dictionary for the new pulse sequence 5. make custom processing method for the new pulse sequence

'''
