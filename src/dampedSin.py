"""
Created on Fri Oct 11 16:30:54 2013
Each model is referred to using a modelname and must contain must contain three methods
  intializemodelname
  modelname
  fitmodelname
damped sin  Signal = a*(sin(pi/2*t/t90) * np.exp(-t/tau))
last modification: 6-3-14
"""

import lmfit
import numpy as np


def initialize (nParam=None,t=None, s=None):    
    """initialize parameters for damped sine model, t=time array, s=signal array"""
    nparams =3      #max number of parameters, some may be fixed
    if nParam!=None:
        return nparams
    params = lmfit.Parameters()   #define parameter dictionary
    paramlist = []    # list of parameters used for this model
    params.add('tau', value= t[-1],  vary = True)
    paramlist.append('tau')
    params.add('a', value= np.amax(s), vary = True)
    paramlist.append('a')
    params.add('t90',value=20 ,  min=0, vary = True)  #value= t[s.argmax()] assume that the maximum occurs at 90 deg if it is a damped sin wave
    paramlist.append('t90')
    return [params,paramlist]

# define objective function: returns the array to be minimized
def dSin(params, t, s):
    """ damped sin model"""
    a = params['a'].value
    t90 = params['t90'].value
    tau = params['tau'].value
    b=np.pi/t90/2
    model = a*np.sin(b*t) * np.exp(-t/tau)
    return (model - s)

def fitdSin(params, t, s):
    """fits signal vs t data to damped sin model"""
    result = lmfit.minimize(dSin, params, args=(t, s))
    final = s + result.residual
    return final
