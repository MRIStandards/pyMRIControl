'''
Created on Jun 16, 2023

@author: mrlab

*********************************************
 * modified VBScript-NMRScript Header, v2.4-060608
 *
 * use 'TNMR.App.CommandName' to communicate 
 * with the Application Object
 * use 'Data.CommandName' to communicate 
 * with the topmost data file (Document Object)

    Dim App, Data, pathToDoc
    Set App = GetObject(, "NTNMR.Application")
    pathToDoc = TNMR.App.GetActiveDocPath

    If pathToDoc="" Then 'if no data file exists
       MsgBox "Need a proper data file to be opened!", vbOKOnly, "NMRScript"
       WScript.Quit() 'quit running the scripting program
    End If 
 
    Set Data = GetObject(pathToDoc)
 ********************************************
 '''
from TNMR import TNMR       #contains code to control TNMR software from Python
# Dim SampleInterface
# Set SampleInterface = CreateObject("SampleInterface.NMRSampleInterface")
# SampleInterface.SpinRateSetpoint = 0

def AutoShimBBnoSpin():
    Delay ="1s"
    Precision = 0.01
    LockorFid = 1
    Step = "2400"
    app.processEvents()
    
    TNMR.App.SetAutoShimParameters (Delay, Precision, LockorFid, Step)
    
    TNMR.App.ActivateShims( "Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, Y")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, XZ")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Y, YZ")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "XY, X2-Y2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z3, Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z4, Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z5, Z3")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z3, Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, Y")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, XZ")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Y, YZ")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "XY, X2-Y2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, XZ, Z2X")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Y, YZ, Z2Y")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "ZXY, XY")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X2-Y2, Z(X2-Y2)")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "X, X3")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Y, Y3")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z1, Z2")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    TNMR.App.ActivateShims( "Z3, Z4")
    
    TNMR.App.StartShims()
    while TNMR.App.CheckShimProgress(): app.processEvents()
    
    
