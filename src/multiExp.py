"""
Created on Fri Oct 11 16:30:54 2013
Each model is referred to using a modelname and must contain must contain three methods
  intializemodelname
  modelname
  fitmodelname

last modification: 6-3-14
"""

import lmfit
import numpy as np


def initialize (nTimeConstants=1,t=None, s=None, VaryBaseline=False):    
    """initialize parameters for multiExp model, t=time array, s=signal array"""
    params = lmfit.Parameters()   #define parameter dictionary
    paramlist = []    # list of parameters used for this model
    params.add('t1', value= t[-1],  min=0, vary = True)
    paramlist.append('t1')
    params.add('A', value= np.amax(s)/2,  vary = True)
    paramlist.append('A')
    
    if nTimeConstants>=2:
        params.add('t2', value= t[-1]/100,  min=0,  vary = True)
        paramlist.append('t2')
        params.add('B', value= np.amax(s)/2, vary = True)
        paramlist.append('B')
    else:
        params.add('t2', value= 1,  min=0,  vary = False)
        paramlist.append('t2')
        params.add('B', value= 0, vary = False)
        paramlist.append('B')
        
    if nTimeConstants>=3:
        params.add('t3', value= t[-1]/1000,  min=0,  vary = True)
        paramlist.append('t3')
        params.add('C', value= np.amax(s)/2, vary = True)
        paramlist.append('C')
    else:
        params.add('t3', value= 1,  min=0,  vary = False)
        paramlist.append('t3')
        params.add('C', value= 0, vary = False)
        paramlist.append('C')

    if VaryBaseline:
        params.add('baseline', value= 0, vary = True)
    else:
        params.add('baseline', value= 0, vary = False)
    paramlist.append('baseline')
    return [params,paramlist]

# define objective function: returns the array to be minimized
def mExp(params, t, s):
    """ multiExponential model"""
    A = params['A'].value
    B = params['B'].value
    C = params['C'].value
    baseline = params['baseline'].value
    t1 = params['t1'].value
    t2 = params['t2'].value
    t3 = params['t3'].value
    model = A*np.exp(-t/t1) +B*np.exp(-t/t2) +C*np.exp(-t/t3)+ baseline
    return (model - s)

def fitmExp(params, t, s):
    """fits signal vs t data to multiExp model"""
    result = lmfit.minimize(mExp, params, args=(t, s))
    final = s + result.residual
    return final
