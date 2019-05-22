#!/usr/bin/env python
# -*- coding: latin-1 -*-
#
#   Copyright 2016 Blaise Frederick
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
#
# $Author: frederic $
#       $Date: 2016/07/11 14:50:43 $
#       $Id: showxcorr,v 1.41 2016/07/11 14:50:43 frederic Exp $
#
from __future__ import print_function, division

# import matplotlib
# matplotlib.use('TkAgg')
from matplotlib.pyplot import plot, show, figure

import time
import sys
import os
import platform

import numpy as np
import scipy as sp
# import gc
import getopt
import rapidtide.miscmath as tide_math
import rapidtide.stats as tide_stats
import rapidtide.util as tide_util
import rapidtide.io as tide_io
import rapidtide.filter as tide_filt
import rapidtide.fit as tide_fit
import rapidtide.resample as tide_resample
import rapidtide.correlate as tide_corr
import rapidtide.multiproc as tide_multiproc
import rapidtide.glmpass as tide_glmpass

from scipy.signal import welch, savgol_filter
from scipy.stats import kurtosis, skew
#from skimage.filters import threshold_triangle  # , apply_hysteresis_threshold
from statsmodels.robust import mad

import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)

try:
    import mkl

    mklexists = True
except ImportError:
    mklexists = False

try:
    import rapidtide.dlfilter as tide_dlfilt

    dlfilterexists = True
    print('dlfilter exists')
except ImportError:
    dlfilterexists = False
    print('dlfilter does not exist')


def usage():
    print(os.path.basename(sys.argv[0]), "- Hypersampling by Analytic Phase Projection - Yay!")
    print("")
    print("usage: ", os.path.basename(sys.argv[0]), " fmrifile slicetimefile outputroot")
    print("")
    print("required arguments:")
    print("    fmrifile:                      - NIFTI file containing BOLD fmri data")
    print("    slicetimefile:                 - Text file containing the offset time in seconds of each slice relative")
    print("                                     to the start of the TR, one value per line, OR the BIDS sidecar JSON file")
    print("                                     for the fmrifile (contains the SliceTiming field")
    print("    outputroot:                    - Base name for all output files")
    print("")
    print("optional arguments:")
    print("")
    print("Processing steps:")
    print(
        "    --cardcalconly                 - Stop after all cardiac regressor calculation steps (before phase projection).")
    print(
        "    --dodlfilter                   - Refine cardiac waveform from the fMRI data using a deep learning filter.")
    print("                                     NOTE: this will only work if you have a working Keras installation;")
    print("                                     if not, this option is ignored.")
    print(
        "                                     OTHER NOTE: Some versions of tensorflow seem to have some weird conflict")
    print("                                     with MKL which I can't seem to be able to fix.  If the dl filter bombs")
    print("                                     complaining about multiple openmp libraries, try rerunning with the")
    print(
        "                                     secret and inadvisable '--usesuperdangerousworkaround' flag.  Good luck!")
    print(
        "    --model=MODELNAME              - Use model MODELNAME for dl filter (default is model_revised - from the revised NeuroImage paper.)")
#    print("    --glm                          - Generate voxelwise aliased synthetic cardiac regressors and filter")
#    print("                                     them out")
#    print("    --temporalglm                  - Perform temporal rather than spatial GLM")
    print("")
    print("Performance:")
    print(
        "    --mklthreads=NTHREADS          - Use NTHREADS MKL threads to accelerate processing (defaults to 1 - more")
    print("                                     threads up to the number of cores can accelerate processing a lot, but")
    print(
        "                                     can really kill you on clusters unless you're very careful.  Use at your")
    print("                                     own risk.)")
    print("")
    print("Preprocessing:")
    print("    --numskip=SKIP                 - Skip SKIP tr's at the beginning of the fmri file (default is 0).")
    print(
        "    --motskip=SKIP                 - Skip SKIP tr's at the beginning of the motion regressor file (default is 0).")
    print("    --motionfile=MOTFILE[:COLSPEC] - Read 6 columns of motion regressors out of MOTFILE text file.")
    print("                                     (with timepoints rows) and regress them, their derivatives, ")
    print("                                     and delayed derivatives out of the data prior to analysis.")
    print("                                     If COLSPEC is present, use the comma separated list of ranges to")
    print("                                     specify X, Y, Z, RotX, RotY, and RotZ, in that order.  For")
    print("                                     example, :3-5,7,0,9 would use columns 3, 4, 5, 7, 0 and 9")
    print("                                     for X, Y, Z, RotX, RotY, RotZ, respectively")
    print("    --motionhp=HPFREQ              - Highpass filter motion regressors to HPFREQ Hz prior to regression")
    print("    --motionlp=LPFREQ              - Lowpass filter motion regressors to HPFREQ Hz prior to regression")
    print("")
    print("Cardiac estimation tuning:")
    print(
        "    --varmaskthreshpct=PCT         - Only include voxels with MAD over time in the PCTth percentile and higher in")
    print(
        "                                     the generation of the cardiac waveform (default is no variance masking.)")
    print("    --estmask=MASKNAME             - Generation of cardiac waveform from data will be restricted to")
    print("                                     voxels in MASKNAME and weighted by the mask intensity (overrides")
    print("                                     normal variance mask.)")
    print(
        "    --minhr=MINHR                  - Limit lower cardiac frequency search range to MINHR BPM (default is 40)")
    print(
        "    --maxhr=MAXHR                  - Limit upper cardiac frequency search range to MAXHR BPM (default is 140)")
    print("    --minhrfilt=MINHR              - Highpass filter cardiac waveform estimate to MINHR BPM (default is 40)")
    print(
        "    --maxhrfilt=MAXHR              - Lowpass filter cardiac waveform estimate to MAXHR BPM (default is 1000)")
    print(
        "    --envcutoff=CUTOFF             - Lowpass filter cardiac normalization envelope to CUTOFF Hz (default is 0.4)")
    print("    --notchwidth=WIDTH             - Set the width of the notch filter, in percent of the notch frequency")
    print("                                     (default is 1.5)")

    print("")
    print("External cardiac waveform options:")
    print("    --cardiacfile=FILE[:COL]       - Read the cardiac waveform from file FILE.  If COL is an integer,")
    print("                                     format json file, use column named COL (if no file is specified ")
    print("                                     is specified, estimate cardiac signal from data)")
    print("    --cardiacfreq=FREQ             - Cardiac waveform in cardiacfile has sample frequency FREQ ")
    print("                                     (default is 32Hz). NB: --cardiacfreq and --cardiactstep")
    print("                                     are two ways to specify the same thing")
    print("    --cardiactstep=TSTEP           - Cardiac waveform in file has sample time step TSTEP ")
    print("                                     (default is 0.03125s) NB: --cardiacfreq and --cardiactstep")
    print("                                     are two ways to specify the same thing")
    print("    --cardiacstart=START           - The time delay in seconds into the cardiac file, corresponding")
    print("                                     in the first TR of the fmri file (default is 0.0)")
    print("    --stdfreq=FREQ                 - Frequency to which the cardiac signals are resampled for output.")
    print("                                     Default is 25.")
    print("    --forcehr=BPM                  - Force heart rate fundamental detector to be centered at BPM")
    print("                                     (overrides peak frequencies found from spectrum).  Useful")
    print("                                     if there is structured noise that confuses the peak finder.")
    print("")
    print("Phase projection tuning:")
    print("    --outputbins=BINS              - Number of output phase bins (default is 32)")
    print("    --gridbins=BINS                - Width of the gridding kernel in output phase bins (default is 3.0)")
    print("    --gridkernel=KERNEL            - Convolution gridding kernel.  Options are 'old', 'gauss', and 'kaiser'")
    print("                                     (default is 'kaiser')")
    print("    --projmask=MASKNAME            - Phase projection will be restricted to voxels in MASKNAME")
    print("                                     (overrides normal intensity mask.)")
    print("    --projectwithraw               - Use fmri derived cardiac waveform as phase source for projection, even")
    print("                                     if a plethysmogram is supplied")
    print("")
    print("Debugging arguments (probably not of interest to users):")
    print("    --debug                        - Turn on debugging information")
    print("    --nodetrend                    - Disable data detrending")
    print("    --noorthog                     - Disable orthogonalization of motion confound regressors")
    print("    --normalize                    - Normalize fmri data")
    print("    --nodemean                     - Do not demean fmri data")
    print("    --disablenotch                 - Disable subharmonic notch filter")
    print("    --nomask                       - Disable data masking for calculating cardiac waveform")
    print("    --nocensor                     - Bad points will not be excluded from analytic phase projection")
    print("    --noappsmooth                  - Disable smoothing app file in the phase direction")
    print("    --nophasefilt                  - Disable the phase trend filter (probably not a good idea)")
    print("    --nocardiacalign               - Disable alignment of pleth signal to fmri derived cardiac signal.")
    print("                                     to blood vessels")
    print("    --saveinfoasjson               - Save the info file in json format rather than text.  Will eventually")
    print("    --trimcorrelations             - Some physiological timecourses don't cover the entire length of the")
    print("                                     fMRI experiment.  Use this option to trim other waveforms to match ")
    print("                                     when calculating correlations.")

    return ()


def rrifromphase(timeaxis, thephase):
    return None


def cardiacsig(thisphase, amps=[1.0, 0.0, 0.0], phases=None, overallphase=0.0):
    total = 0.0
    if phases is None:
        phases = amps * 0.0
    for i in range(len(amps)):
        total += amps[i] * np.cos((i + 1) * thisphase + phases[i] + overallphase)
    return total


def physiofromimage(normdata_byslice,
                    mask_byslice,
                    numslices,
                    timepoints,
                    tr,
                    slicetimes,
                    cardprefilter,
                    respprefilter,
                    notchpct=1.5,
                    madnorm=True,
                    nprocs=1,
                    debug=False,
                    verbose=False,
                    usemask=True):
    # find out what timepoints we have, and their spacing
    numsteps, minstep, sliceoffsets = tide_io.sliceinfo(slicetimes, tr)
    print(len(slicetimes), 'slice times with', numsteps, 'unique values - diff is', minstep)

    # make slice means
    print('making slice means...')
    hirestc = np.zeros((timepoints * numsteps), dtype=np.float64)
    sliceavs = np.zeros((numslices, timepoints), dtype=np.float64)
    if not verbose:
        print('averaging slices...')
    for theslice in range(numslices):
        if verbose:
            print('averaging slice', theslice)
        if usemask:
            validvoxels = np.where(mask_byslice[:, theslice] > 0)[0]
        else:
            validvoxels = np.where(mask_byslice[:, theslice] >= 0)[0]
        if len(validvoxels) > 0:
            if madnorm:
                sliceavs[theslice, :] = tide_math.madnormalize(np.mean(
                    normdata_byslice[validvoxels, theslice, :] * mask_byslice[validvoxels, theslice, np.newaxis],
                    axis=0))
            else:
                sliceavs[theslice, :] = np.mean(
                    normdata_byslice[validvoxels, theslice, :] * mask_byslice[validvoxels, theslice, np.newaxis],
                    axis=0)
            for t in range(timepoints):
                hirestc[numsteps * t + sliceoffsets[theslice]] += sliceavs[theslice, t]
    if not verbose:
        print('done')
    slicesamplerate = 1.0 * numsteps / tr
    print('slice sample rate is ', slicesamplerate)

    # delete the TR frequency and the first subharmonic
    print('notch filtering...')
    filthirestc = tide_filt.harmonicnotchfilter(hirestc, slicesamplerate, 1.0 / tr, notchpct=notchpct, debug=debug)

    # now get the cardiac and respiratory waveforms
    hirescardtc = -1.0 * tide_math.madnormalize(cardprefilter.apply(slicesamplerate, filthirestc))
    hiresresptc = -1.0 * tide_math.madnormalize(respprefilter.apply(slicesamplerate, filthirestc))

    return tide_math.madnormalize(hirescardtc), tide_math.madnormalize(hiresresptc), slicesamplerate, numsteps


def savgolsmooth(data, smoothlen=101, polyorder=3):
    return savgol_filter(data, smoothlen, polyorder)


def getfundamental(inputdata, Fs, fundfreq):
    arb_lower = 0.71 * fundfreq
    arb_upper = 1.4 * fundfreq
    arb_lowerstop = 0.9 * arb_lower
    arb_upperstop = 1.1 * arb_upper
    thefundfilter = tide_filt.noncausalfilter(filtertype='arb')
    thefundfilter.setarb(arb_lowerstop, arb_lower, arb_upper, arb_upperstop)
    return thefundfilter.apply(Fs, inputdata)


def getcardcoeffs(cardiacwaveform, slicesamplerate, minhr=40.0, maxhr=140.0, smoothlen=101, debug=False, display=False):
    if len(cardiacwaveform) > 1024:
        thex, they = welch(cardiacwaveform, slicesamplerate, nperseg=1024)
    else:
        thex, they = welch(cardiacwaveform, slicesamplerate)
    initpeakfreq = np.round(thex[np.argmax(they)] * 60.0, 2)
    if initpeakfreq > maxhr:
        initpeakfreq = maxhr
    if initpeakfreq < minhr:
        initpeakfreq = minhr
    if debug:
        print('initpeakfreq:', initpeakfreq, 'BPM')
    freqaxis, spectrum = tide_filt.spectrum(tide_filt.hamming(len(cardiacwaveform)) * cardiacwaveform,
                                            Fs=slicesamplerate,
                                            mode='complex')
    # remove any spikes at zero frequency
    minbin = int(minhr // (60.0 * (freqaxis[1] - freqaxis[0])))
    maxbin = int(maxhr // (60.0 * (freqaxis[1] - freqaxis[0])))
    spectrum[:minbin] = 0.0
    spectrum[maxbin:] = 0.0

    # find the max
    ampspec = savgolsmooth(np.abs(spectrum), smoothlen=smoothlen)
    if display:
        figure()
        plot(freqaxis, ampspec, 'r')
        show()
    peakfreq = freqaxis[np.argmax(ampspec)]
    if debug:
        print('cardiac fundamental frequency is', np.round(peakfreq * 60.0, 2), 'BPM')
    normfac = np.sqrt(2.0) * tide_math.rms(cardiacwaveform)
    if debug:
        print('normfac:', normfac)
    return peakfreq


def normalizevoxels(fmri_data, detrendorder, validvoxels, time, timings):
    print('normalizing voxels...')
    normdata = fmri_data * 0.0
    demeandata = fmri_data * 0.0
    starttime = time.time()
    # detrend if we are going to
    numspatiallocs = fmri_data.shape[0]
    reportstep = int(numspatiallocs // 100)
    if detrendorder > 0:
        print('detrending to order', detrendorder, '...')
        for idx, thevox in enumerate(validvoxels):
            if (idx % reportstep == 0) or (idx == len(validvoxels) - 1):
                tide_util.progressbar(idx + 1, len(validvoxels), label='Percent complete')
            fmri_data[thevox, :] = tide_fit.detrend(fmri_data[thevox, :], order=detrendorder, demean=False)
        timings.append(['Detrending finished', time.time(), numspatiallocs, 'voxels'])
        print(' done')

    means = np.mean(fmri_data[:, :], axis=1).flatten()
    demeandata[validvoxels, :] = fmri_data[validvoxels, :] - means[validvoxels, None]
    normdata[validvoxels, :] = np.nan_to_num(demeandata[validvoxels, :] / means[validvoxels, None])
    timings.append(['Normalization finished', time.time(), numspatiallocs, 'voxels'])
    print('normalization took', time.time() - starttime, 'seconds')
    return normdata, demeandata


def cleancardiac(Fs, plethwaveform, cutoff=0.4, thresh=0.2, nyquist=None, debug=False):
    # first bandpass the cardiac signal to calculate the envelope
    if debug:
        print('entering cleancardiac')
    plethfilter = tide_filt.noncausalfilter('cardiac')
    print('filtering')
    print('envelope detection')
    envelope = tide_math.envdetect(Fs,
                                   tide_math.madnormalize(plethfilter.apply(Fs, tide_math.madnormalize(plethwaveform))),
                                   cutoff=cutoff)
    envmean = np.mean(envelope)

    # now patch the envelope function to eliminate very low values
    envlowerlim = thresh * np.max(envelope)
    envelope = np.where(envelope >= envlowerlim, envelope, envlowerlim)

    # now high pass the plethysmogram to eliminate baseline
    arb_lowerstop, arb_lowerpass, arb_upperpass, arb_upperstop = plethfilter.getfreqlimits()
    plethfilter.settype('arb')
    arb_upper = 10.0
    arb_upperstop = arb_upper * 1.1
    if nyquist is not None:
        if nyquist < arb_upper:
            arb_upper = nyquist
            arb_upperstop = nyquist
    plethfilter.setarb(arb_lowerstop, arb_lowerpass, arb_upperpass, arb_upperstop)
    filtplethwaveform = tide_math.madnormalize(plethfilter.apply(Fs, tide_math.madnormalize(plethwaveform)))
    print('normalizing')
    normpleth = tide_math.madnormalize(envmean * filtplethwaveform / envelope)

    # return the filtered waveform, the normalized waveform, and the envelope
    if debug:
        print('leaving cleancardiac')
    return filtplethwaveform, normpleth, envelope


def findbadpts(thewaveform, nameroot, outputroot, samplerate, infodict,
               thetype='mad',
               retainthresh=0.89,
               mingap=2.0,
               outputlevel=0,
               debug=True):
    #if thetype == 'triangle' or thetype == 'mad':
    if thetype == 'mad':
        absdev = np.fabs(thewaveform - np.median(thewaveform))
        #if thetype == 'triangle':
        #    thresh = threshold_triangle(np.reshape(absdev, (len(absdev), 1)))
        medianval = np.median(thewaveform)
        sigma = mad(thewaveform, center=medianval)
        numsigma = np.sqrt(1.0 / (1.0 - retainthresh))
        thresh = numsigma * sigma
        thebadpts = np.where(absdev >= thresh, 1.0, 0.0)
        print('bad point threshhold set to', thresh, 'using the', thetype, 'method for', nameroot)
    elif thetype == 'fracval':
        lower, upper = tide_stats.getfracvals(thewaveform, [(1.0 - retainthresh) / 2.0, (1.0 + retainthresh) / 2.0],
                                              numbins=200)
        therange = upper - lower
        lowerthresh = lower - therange
        upperthresh = upper + therange
        thebadpts = np.where((lowerthresh <= thewaveform) & (thewaveform <= upperthresh), 0.0, 1.0)
        thresh = (lowerthresh, upperthresh)
        print('values outside of ', lowerthresh, 'to', upperthresh, 'marked as bad using the', thetype, 'method for',
              nameroot)
    else:
        print('bad thresholding type')
        sys.exit()

    # now fill in gaps
    streakthresh = int(np.round(mingap * samplerate))
    lastbad = 0
    if thebadpts[0] == 1.0:
        isbad = True
    else:
        isbad = False
    for i in range(1, len(thebadpts)):
        if thebadpts[i] == 1.0:
            if not isbad:
                # streak begins
                isbad = True
                if i - lastbad < streakthresh:
                    thebadpts[lastbad:i] = 1.0
            lastbad = i
        else:
            isbad = False
    if len(thebadpts) - lastbad - 1 < streakthresh:
        thebadpts[lastbad:] = 1.0

    if outputlevel > 0:
        tide_io.writevec(thebadpts, outputroot + '_' + nameroot + '_badpts.txt')
    infodict[nameroot + '_threshvalue'] = thresh
    infodict[nameroot + '_threshmethod'] = thetype
    return thebadpts


def approximateentropy(waveform, m, r):
    def _maxdist(x_i, x_j):
        return max([abs(ua - va) for ua, va in zip(x_i, x_j)])

    def _phi(m):
        x = [[waveform[j] for j in range(i, i + m - 1 + 1)] for i in range(N - m + 1)]
        C = [len([1 for x_j in x if _maxdist(x_i, x_j) <= r]) / (N - m + 1.0) for x_i in x]
        return (N - m + 1.0) ** (-1) * sum(np.log(C))

    N = len(waveform)

    return abs(_phi(m + 1) - _phi(m))


def entropy(waveform):
    return -np.sum(np.square(waveform) * np.nan_to_num(np.log2(np.square(waveform))))


def plethquality(waveform, Fs, S_windowsecs=5.0, K_windowsecs=60.0, E_windowsecs=1.0, detrendorder=8, debug=False):
    """

    Parameters
    ----------
    waveform: array-like
        The cardiac waveform to be assessed
    Fs: float
        The sample rate of the data
    S_windowsecs: float
        Skewness window duration in seconds.  Defaults to 5.0 (optimal for discrimination of "good" from "acceptable"
        and "unfit" according to Elgendi)
    K_windowsecs: float
        Skewness window duration in seconds.  Defaults to 2.0 (after Selveraj)
    E_windowsecs: float
        Entropy window duration in seconds.  Defaults to 0.5 (after Selveraj)
    detrendorder: int
        Order of detrending polynomial to apply to plethysmogram.
    debug: boolean
        Turn on extended output

    Returns
    -------
    S_sqi_mean: float
        The mean value of the quality index over all time
    S_std_mean: float
        The standard deviation of the quality index over all time
    S_waveform: array
        The quality metric over all timepoints
    K_sqi_mean: float
        The mean value of the quality index over all time
    K_std_mean: float
        The standard deviation of the quality index over all time
    K_waveform: array
        The quality metric over all timepoints
    E_sqi_mean: float
        The mean value of the quality index over all time
    E_std_mean: float
        The standard deviation of the quality index over all time
    E_waveform: array
        The quality metric over all timepoints


    Calculates the windowed skewness, kurtosis, and entropy quality metrics described in Elgendi, M.
    "Optimal Signal Quality Index for Photoplethysmogram Signals". Bioengineering 2016, Vol. 3, Page 21 3, 21 (2016).
    """
    # detrend the waveform
    dt_waveform = tide_fit.detrend(waveform, order=detrendorder, demean=True)

    # calculate S_sqi and K_sqi over a sliding window.  Window size should be an odd number of points.
    S_windowpts = int(np.round(S_windowsecs * Fs, 0))
    S_windowpts += 1 - S_windowpts % 2
    S_waveform = dt_waveform * 0.0
    K_windowpts = int(np.round(K_windowsecs * Fs, 0))
    K_windowpts += 1 - K_windowpts % 2
    K_waveform = dt_waveform * 0.0
    E_windowpts = int(np.round(E_windowsecs * Fs, 0))
    E_windowpts += 1 - E_windowpts % 2
    E_waveform = dt_waveform * 0.0

    if debug:
        print('S_windowsecs, S_windowpts:', S_windowsecs, S_windowpts)
        print('K_windowsecs, K_windowpts:', K_windowsecs, K_windowpts)
        print('E_windowsecs, E_windowpts:', E_windowsecs, E_windowpts)
    for i in range(0, len(dt_waveform)):
        startpt = np.max([0, i - S_windowpts // 2])
        endpt = np.min([i + S_windowpts // 2, len(dt_waveform)])
        S_waveform[i] = skew(dt_waveform[startpt:endpt + 1], nan_policy='omit')

        startpt = np.max([0, i - K_windowpts // 2])
        endpt = np.min([i + K_windowpts // 2, len(dt_waveform)])
        K_waveform[i] = kurtosis(dt_waveform[startpt:endpt + 1], fisher=False)

        startpt = np.max([0, i - E_windowpts // 2])
        endpt = np.min([i + E_windowpts // 2, len(dt_waveform)])
        # E_waveform[i] = entropy(dt_waveform[startpt:endpt + 1])
        r = 0.2 * np.std(dt_waveform[startpt:endpt + 1])
        E_waveform[i] = approximateentropy(dt_waveform[startpt:endpt + 1], 2, r)
        if debug:
            print(i, startpt, endpt, endpt - startpt + 1, S_waveform[i], K_waveform[i], E_waveform[i])

    S_sqi_mean = np.mean(S_waveform)
    S_sqi_std = np.std(S_waveform)
    K_sqi_mean = np.mean(K_waveform)
    K_sqi_std = np.std(K_waveform)
    E_sqi_mean = np.mean(E_waveform)
    E_sqi_std = np.std(E_waveform)

    return S_sqi_mean, S_sqi_std, S_waveform, K_sqi_mean, K_sqi_std, K_waveform, E_sqi_mean, E_sqi_std, E_waveform


def getphysiofile(cardiacfile, colnum, colname,
                  inputfreq, inputstart, slicetimeaxis, stdfreq,
                  envcutoff, envthresh,
                  timings, infodict, outputroot, outputlevel=0, debug=False):
    if debug:
        print('entering getphysiofile')
    print('reading cardiac signal from file')
    infodict['cardiacfromfmri'] = False

    # check file type
    filebase, extension = os.path.splitext(cardiacfile)
    if debug:
        print('filebase:', filebase)
        print('extension:', extension)
    if extension == '.json':
        inputfreq, inputstart, pleth_fullres = tide_io.readcolfrombidstsv(cardiacfile, columnname=colname,
                                                                          columnnum=colnum, debug=debug)
    else:
        pleth_fullres = np.transpose(tide_io.readvecs(cardiacfile))
        print(pleth_fullres.shape)
        if len(pleth_fullres.shape) != 1:
            pleth_fullres = pleth_fullres[:, colnum]
    if debug:
        print('inputfreq:', inputfreq)
        print('inputstart:', inputstart)
        print('pleth_fullres:', pleth_fullres)
    inputtimeaxis = sp.arange(0.0, (1.0 / inputfreq) * len(pleth_fullres), 1.0 / inputfreq) + inputstart
    if inputtimeaxis[0] > 0.0 or inputtimeaxis[-1] < slicetimeaxis[-1]:
        print('getphysiofile: error - plethysmogram waveform does not cover the fmri time range')
        sys.exit()
    if debug:
        print('pleth_fullres: len=', len(pleth_fullres), 'vals=', pleth_fullres)
        print('inputfreq =', inputfreq)
        print('inputstart =', inputstart)
        print('inputtimeaxis: len=', len(inputtimeaxis), 'vals=', inputtimeaxis)
    timings.append(['Cardiac signal from physiology data read in', time.time(), None, None])

    # filter and amplitude correct the waveform to remove gain fluctuations
    cleanpleth_fullres, normpleth_fullres, plethenv_fullres = cleancardiac(inputfreq, pleth_fullres,
                                                                           cutoff=envcutoff,
                                                                           thresh=envthresh,
                                                                           nyquist=inputfreq / 2.0,
                                                                           debug=debug)
    infodict['plethsamplerate'] = inputfreq
    infodict['numplethpts_fullres'] = len(pleth_fullres)

    if outputlevel > 0:
        tide_io.writevec(pleth_fullres, outputroot + '_rawpleth_native.txt')
        tide_io.writevec(cleanpleth_fullres, outputroot + '_pleth_native.txt')
        tide_io.writevec(plethenv_fullres, outputroot + '_cardenvelopefromfile_native.txt')
    timings.append(['Cardiac signal from physiology data cleaned', time.time(), None, None])

    # resample to slice time resolution and save
    pleth_sliceres = tide_resample.doresample(inputtimeaxis, cleanpleth_fullres, slicetimeaxis, method='univariate',
                                              padlen=0)
    infodict['numplethpts_sliceres'] = len(pleth_sliceres)

    # resample to standard resolution and save
    pleth_stdres = tide_math.madnormalize(
        tide_resample.arbresample(cleanpleth_fullres, inputfreq, stdfreq, decimate=True, debug=True))
    infodict['numplethpts_stdres'] = len(pleth_stdres)

    timings.append(
        ['Cardiac signal from physiology data resampled to slice resolution and saved', time.time(), None, None])

    if debug:
        print('leaving getphysiofile')
    return pleth_sliceres, pleth_stdres


def readextmask(thefilename, nim_hdr, xsize, ysize, numslices):
    extmask, extmask_data, extmask_hdr, theextmaskdims, theextmasksizes = tide_io.readfromnifti(thefilename)
    xsize_extmask, ysize_extmask, numslices_extmask, timepoints_extmask = tide_io.parseniftidims(theextmaskdims)
    if not tide_io.checkspacematch(nim_hdr, extmask_hdr):
        print('Dimensions of mask do not match the fmri data - exiting')
        sys.exit()
    if timepoints_extmask > 1:
        print('Mask must have only 3 dimensions - exiting')
        sys.exit()
    return extmask_data.reshape(xsize * ysize, numslices)


def checkcardmatch(reference, candidate, samplerate, refine=True, debug=False):
    thecardfilt = tide_filt.noncausalfilter(filtertype='cardiac')
    trimlength = np.min([len(reference), len(candidate)])
    thexcorr = tide_corr.fastcorrelate(
        tide_math.corrnormalize(thecardfilt.apply(samplerate, reference),
                                prewindow=True,
                                detrendorder=3,
                                windowfunc='hamming')[:trimlength],
        tide_math.corrnormalize(thecardfilt.apply(samplerate, candidate),
                                prewindow=True,
                                detrendorder=3,
                                windowfunc='hamming')[:trimlength],
        usefft=True)
    xcorrlen = len(thexcorr)
    sampletime = 1.0 / samplerate
    xcorr_x = np.r_[0.0:xcorrlen] * sampletime - (xcorrlen * sampletime) / 2.0 + sampletime / 2.0
    searchrange = 5.0
    trimstart = tide_util.valtoindex(xcorr_x, -2.0 * searchrange)
    trimend = tide_util.valtoindex(xcorr_x, 2.0 * searchrange)
    maxindex, maxdelay, maxval, maxsigma, maskval, failreason, peakstart, peakend = tide_fit.findmaxlag_gauss(
        xcorr_x[trimstart:trimend], thexcorr[trimstart:trimend], -searchrange, searchrange, 3.0,
        refine=refine,
        zerooutbadfit=False,
        useguess=False,
        fastgauss=False,
        displayplots=False)
    if debug:
        print('CORRELATION: maxindex, maxdelay, maxval, maxsigma, maskval, failreason, peakstart, peakend:',
              maxindex, maxdelay, maxval, maxsigma, maskval, failreason, peakstart, peakend)
    return maxval, maxdelay, failreason


def happy_main(thearguments):
    # get the command line parameters
    debug = False
    fmrimod = 'demean'
    centric = True
    histlen = 100
    doplot = False
    smoothlen = 101
    envcutoff = 0.4
    envthresh = 0.2
    maskthreshpct = 10.0
    varmaskthreshpct = 75.0
    varmasktype = 'mad'
    varmaskbyslice = False
    usevarmask = False
    upsamplefac = 100
    destpoints = 32
    congridbins = 3.0
    gridkernel = 'kaiser'
    cardiacfilename = None
    colnum = None
    colname = None
    inputfreq = 32.0
    inputstart = 0.0
    doglm = False
    notchpct = 1.5
    minhr = 40.0
    maxhr = 140.0
    minhrfilt = 40.0
    maxhrfilt = 1000.0
    softvesselfrac = 0.4
    infodict = {}
    stdfreq = 25.0
    nprocs = 1
    mklthreads = 1
    spatialglmdenoise = True
    savecardiacnoise = True
    forcedhr = None
    usemaskcardfromfmri = True
    censorbadpts = True
    estmaskname = None
    projmaskname = None
    detrendorder = 3
    filtphase = True
    savemotionglmfilt = False
    motionfilename = None
    cardcalconly = False
    domadnorm = True
    numskip = 0
    motskip = 0
    dodlfilter = False
    modelname = 'model_revised'
    motionhp = None
    motionlp = None
    motfilt_pos = False
    motfilt_deriv = True
    motfilt_derivdelayed = True
    orthogonalize = True
    mpfix = False
    aligncardiac = True
    projectwithraw = False
    saveinfoasjson = False
    savetcsastsv = True
    outputlevel = 1
    verbose = False
    smoothapp = True

    # start the clock!
    timings = [['Start', time.time(), None, None]]

    print(
        "***********************************************************************************************************************************")
    print("NOTICE:  This program is NOT released yet - it's a work in progress and is nowhere near done.  That's why")
    print("there's no documentation or mention in the release notes.  If you want to play with it, be my guest, but be")
    print("aware of the following:")
    print("    1) Any given version of this program may or may not work, or may work in a way different than ")
    print("       a) previous versions, b) what I say it does, c) what I think it does, and d) what you want it to do.")
    print(
        "    2) I am intending to write a paper on this, and if you take this code and scoop me, I'll be peeved. That's just rude.")
    print("    3) For all I know this program might burn down your house, leave your milk out of the refrigerator, or ")
    print("       poison your dog.  USE AT YOUR OWN RISK.")
    print(
        "***********************************************************************************************************************************")
    print("")

    fmrifilename = thearguments[1]
    slicetimename = thearguments[2]
    outputroot = thearguments[3]

    infodict['fmrifilename'] = fmrifilename
    infodict['slicetimename'] = slicetimename
    infodict['outputroot'] = outputroot

    tide_util.savecommandline(thearguments, outputroot)

    # now scan for optional arguments
    try:
        opts, args = getopt.getopt(thearguments[4:], "x", ["cardiacfile=",
                                                           "cardiacfreq=",
                                                           "cardiactstep=",
                                                           "cardiacstart=",
                                                           "maxhr=",
                                                           "minhr=",
                                                           "maxhrfilt=",
                                                           "minhrfilt=",
                                                           "envcutoff=",
                                                           "envthresh=",
                                                           "notchwidth=",
                                                           "disablenotch",
                                                           "nodetrend",
                                                           "motionfile=",
                                                           "glm",
                                                           "temporalglm",
                                                           "debug",
                                                           "motionhp=",
                                                           "motionlp=",
                                                           "nodemean",
                                                           "cardcalconly",
                                                           "outputbins=",
                                                           "gridbins=",
                                                           "gridkernel=",
                                                           "stdfreq=",
                                                           "nprocs=",
                                                           'mklthreads=',
                                                           "estmask=",
                                                           "projmask=",
                                                           "smoothlen=",
                                                           "forcehr=",
                                                           "numskip=",
                                                           "motskip=",
                                                           "nocensor",
                                                           "noappsmooth",
                                                           "nomadnorm",
                                                           "dodlfilter",
                                                           "noncentric",
                                                           "varmaskthreshpct=",
                                                           "varmaskbyslice",
                                                           "model=",
                                                           "usesuperdangerousworkaround",
                                                           "savemotionglmfilt",
                                                           "saveinfoasjson",
                                                           "savetcsastsv",
                                                           "nophasefilt",
                                                           "projectwithraw",
                                                           "trimcorrelations",
                                                           "nomask",
                                                           "noorthog",
                                                           "nocardiacalign",
                                                           "nomotderiv",
                                                           "nomotderivdelayed",
                                                           "help"])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(str(err))  # will print something like "option -x not recognized"
        usage()
        sys.exit(2)

    for o, a in opts:
        if o == "-x":
            print('got an x')
        elif o == "--motionfile":
            motionfilename = a
            print('Will regress motion out of data prior to analysis')
        elif o == "--glm":
            doglm = True
            print('will generate and remove aliased voxelwise cardiac regressors')
        elif o == "--temporalglm":
            spatialglmdenoise = False
            print('will do a temporal rather than spatial glm')
        elif o == "--disablenotch":
            notchpct = -1.0
            print('Disabling subharmonic notch filter')
        elif o == "--nodetrend":
            detrendorder = 0
            print('will disable data detrending')
        elif o == "--debug":
            debug = True
            print('extended debugging messages')
        elif o == "--savemotionglmfilt":
            savemotionglmfilt = True
        elif o == "--nomask":
            censorbadpts = False
        elif o == "--nophasefilt":
            filtphase = False
            print('disabling phase trend filter')
        elif o == "--varmaskbyslice":
            varmaskbyslice = True
            print('will variance mask by percentile by slice, not volume')
        elif o == "--nocardiacalign":
            aligncardiac = False
            print('disabling cardiac alignment')
        elif o == "--noncentric":
            centric = False
            print('performing noncentric projection')
        elif o == "--dodlfilter":
            if dlfilterexists:
                dodlfilter = True
                print('will apply deep learning filter to enhance the cardiac waveforms')
            else:
                print('dlfilter not found - check to make sure Keras is installed and working.  Disabling.')
        elif o == "--model":
            modelname = a
            print('will use', modelname, 'for the deep learning filter;')
        elif o == "--cardcalconly":
            cardcalconly = True
            print('will stop processing after calculating cardiac waveforms')
        elif o == "--noappsmooth":
            smoothapp = False
            print('will not smooth projection along phase direction')
        elif o == "--nocensor":
            usemaskcardfromfmri = False
            print('will not censor bad points')
        elif o == "--projectwithraw":
            projectwithraw = True
            print('will use fmri derived cardiac waveform as phase source for projection')
        elif o == "--nomadnorm":
            domadnorm = False
            print('disabling MAD normalization between slices')
        elif o == "--outputbins":
            destpoints = int(a)
            print('will use', destpoints, 'output bins')
        elif o == '--numskip':
            numskip = int(a)
            print('Skipping first', numskip, 'fmri trs')
        elif o == '--motskip':
            motskip = int(a)
            print('Skipping first', motskip, 'motion trs')
        elif o == "--smoothlen":
            smoothlen = int(a)
            smoothlen = smoothlen + (1 - smoothlen % 2)
            print('will set savitsky-golay window to', smoothlen)
        elif o == "--gridbins":
            congridbins = float(a)
            print('will use a convolution gridding kernel of width', congridbins, 'bins')
        elif o == "--gridkernel":
            gridkernel = a
            if gridkernel == 'kaiser':
                print('will use a kaiser-bessel gridding kernel')
            elif gridkernel == 'gauss':
                print('will use a gaussian gridding kernel')
            elif gridkernel == 'old':
                print('falling back to old style gridding')
            else:
                print('illegal gridding kernel specified - aborting')
                sys.exit()
        elif o == "--usesuperdangerousworkaround":
            mpfix = True
            print('trying super dangerous workaround to make dlfilter work')
        elif o == "--notchwidth":
            notchpct = float(a)
            print('setting notchwidth to', notchpct, '%')
        elif o == "--nprocs":
            nprocs = int(a)
            if nprocs < 1:
                nprocs = tide_multiproc.maxcpus()
            print('will use', nprocs, 'processors for long calculations')
        elif o == '--mklthreads':
            mklthreads = int(a)
            linkchar = '='
            if mklexists:
                mklmaxthreads = mkl.get_max_threads()
                if mklthreads > mklmaxthreads:
                    print('mkl max threads =', mklmaxthreads, ' - using max')
                    mklthreads = mklmaxthreads

                print('will use', mklthreads, 'MKL threads for accelerated numpy processing.')
            else:
                print('MKL not present - ignoring --mklthreads')
        elif o == "--stdfreq":
            stdfreq = float(a)
            print('setting common output frequency to', stdfreq)
        elif o == "--envcutoff":
            envcutoff = float(a)
            print('will set top of cardiac envelope band to', envcutoff)
        elif o == "--envthresh":
            threshoff = float(a)
            print('will set lowest value of cardiac envelope band to', envthresh, 'x the maximum value')
        elif o == "--minhr":
            newval = float(a)
            print('will set bottom of cardiac search range to', newval, 'BPM from', minhr, 'BPM')
            minhr = newval
        elif o == "--maxhr":
            newval = float(a)
            print('will set top of cardiac search range to', newval, 'BPM from', maxhr, 'BPM')
            maxhr = newval
        elif o == "--minhrfilt":
            newval = float(a)
            print('will set bottom of cardiac band to', newval, 'BPM from', minhrfilt, 'BPM when estimating waveform')
            minhrfilt = newval
        elif o == "--maxhrfilt":
            newval = float(a)
            print('will set top of cardiac band to', newval, 'BPM from', maxhrfilt, 'BPM when estimating waveform')
            maxhrfilt = newval
        elif o == "--forcehr":
            forcedhr = float(a) / 60.0
            print('force heart rate detector to', forcedhr * 60.0, 'BPM')
        elif o == "--motionhp":
            motionhp = float(a)
            print('will highpass motion regressors at', motionhp, 'Hz prior to regression')
        elif o == "--motionlp":
            motionlp = float(a)
            print('will lowpass motion regressors at', motionlp, 'Hz prior to regression')
        elif o == "--savetcsastsv":
            savetcsastsv = True
            print('will save timecourses in BIDS tsv format')
        elif o == "--saveinfoasjson":
            saveinfoasjson = True
            print('will save info file in json format')
        elif o == "--trimcorrelations":
            trimcorrelations = True
            print('will be tolerant of short physiological timecourses')
        elif o == "--nodemean":
            fmrimod = 'none'
            print('will not demean fmri before gridding')
        elif o == "--noorthog":
            orthogonalize = False
            print('will not orthogonalize motion regressors')
        elif o == "--varmaskthreshpct":
            varmaskthreshpct = float(a)
            usevarmask = True
            print('setting varmaskthreshpct to', varmaskthreshpct)
        elif o == "--nomotderivdelayed":
            motfilt_derivdelayed = False
            print('will not use motion position regressors')
        elif o == "--nomotderiv":
            motfilt_deriv = False
            print('will not use motion derivative regressors')
        elif o == '--estmask':
            estmaskname = a
            usemaskcardfromfmri = True
            print('Will restrict cardiac waveform fit to voxels in', estmaskname)
        elif o == '--projmask':
            projmaskname = a
            useintensitymask = False
            usemaskcardfromfmri = True
            print('Will restrict phase projection to voxels in', projmaskname)
        elif o == '--cardiacfile':
            inputlist = a.split(':')
            cardiacfilename = inputlist[0]
            if len(inputlist) > 1:
                try:
                    colnum = int(inputlist[1])
                except ValueError:
                    colname = inputlist[1]
            print('Will use cardiac file', cardiacfilename)
        elif o == '--cardiacfreq':
            inputfreq = float(a)
            print('Setting cardiac sample frequency to ', inputfreq)
        elif o == '--cardiactstep':
            inputfreq = 1.0 / float(a)
            print('Setting cardiac sample time step to ', float(a))
        elif o == '--cardiacstart':
            inputstart = float(a)
            print('Setting cardiac start time to ', inputstart)
        elif o == "--help":
            usage()
            sys.exit()
        else:
            assert False, "unhandled option: " + o


    memfile = open(outputroot + '_memusage.csv', 'w')
    tide_util.logmem(None, file=memfile)

    # set the number of MKL threads to use
    if mklexists:
        mkl.set_num_threads(mklthreads)

    # set up cardiac filter
    arb_lower = minhrfilt / 60.0
    arb_upper = maxhrfilt / 60.0
    thecardbandfilter = tide_filt.noncausalfilter()
    thecardbandfilter.settype('arb')
    arb_lowerstop = arb_lower * 0.9
    arb_upperstop = arb_upper * 1.1
    thecardbandfilter.setarb(arb_lowerstop, arb_lower, arb_upper, arb_upperstop)
    therespbandfilter = tide_filt.noncausalfilter()
    therespbandfilter.settype('resp')
    infodict['filtermaxbpm'] = arb_upper * 60.0
    infodict['filterminbpm'] = arb_lower * 60.0
    infodict['notchpct'] = notchpct
    timings.append(['Argument parsing done', time.time(), None, None])

    # read in the image data
    tide_util.logmem('before reading in fmri data', file=memfile)
    nim, nim_data, nim_hdr, thedims, thesizes = tide_io.readfromnifti(fmrifilename)
    xsize, ysize, numslices, timepoints = tide_io.parseniftidims(thedims)

    # adjust for numskip
    timepoints -= numskip
    nim_data_withskip = nim_data[:, :, :, numskip:]

    xdim, ydim, slicethickness, tr = tide_io.parseniftisizes(thesizes)
    spaceunit, timeunit = nim_hdr.get_xyzt_units()
    if timeunit == 'msec':
        tr /= 1000.0
    mrsamplerate = 1.0 / tr
    print('tr is', tr, 'seconds, mrsamplerate is', mrsamplerate)
    numspatiallocs = int(xsize) * int(ysize) * int(numslices)
    infodict['tr'] = tr
    infodict['mrsamplerate'] = mrsamplerate
    timings.append(['Image data read in', time.time(), None, None])

    # remap to space by time
    fmri_data = np.float64(nim_data_withskip.reshape((numspatiallocs, timepoints)))
    del nim_data

    # remap to voxel by slice by time
    fmri_data_byslice = fmri_data.reshape((xsize * ysize, numslices, timepoints))

    # make and save a mask of the voxels to process based on image intensity
    tide_util.logmem('before mask creation', file=memfile)
    mask = np.uint16(tide_stats.makemask(np.mean(fmri_data[:, :], axis=1),
                                         threshpct=maskthreshpct))
    validvoxels = np.where(mask > 0)[0]
    theheader = nim_hdr
    theheader['dim'][4] = 1
    timings.append(['Mask created', time.time(), None, None])
    if outputlevel > 0:
        tide_io.savetonifti(mask.reshape((xsize, ysize, numslices)), theheader, outputroot + '_mask')
    timings.append(['Mask saved', time.time(), None, None])
    mask_byslice = mask.reshape((xsize * ysize, numslices))

    # read in projection mask if present otherwise fall back to intensity mask
    if projmaskname is not None:
        tide_util.logmem('before reading in projmask', file=memfile)
        projmask_byslice = readextmask(projmaskname, nim_hdr, xsize, ysize, numslices) * np.float64(mask_byslice)
    else:
        projmask_byslice = mask_byslice

    # filter out motion regressors here
    if motionfilename is not None:
        timings.append(['Motion filtering start', time.time(), None, None])
        motionregressors, filtereddata = tide_glmpass.motionregress(motionfilename,
                                                                    fmri_data[validvoxels, :],
                                                                    tr,
                                                                    orthogonalize=orthogonalize,
                                                                    motstart=motskip,
                                                                    motionhp=motionhp,
                                                                    motionlp=motionlp,
                                                                    position=motfilt_pos,
                                                                    deriv=motfilt_deriv,
                                                                    derivdelayed=motfilt_derivdelayed)
        fmri_data[validvoxels, :] = filtereddata[:, :]
        infodict['numorthogmotregressors'] = motionregressors.shape[0]
        timings.append(['Motion filtering end', time.time(), numspatiallocs, 'voxels'])
        tide_io.writenpvecs(motionregressors, outputroot + '_orthogonalizedmotion.txt')
        if savemotionglmfilt:
            tide_io.savetonifti(fmri_data.reshape((xsize, ysize, numslices, timepoints)), theheader,
                                outputroot + '_motionfiltered')
            timings.append(['Motion filtered data saved', time.time(), numspatiallocs, 'voxels'])

    # get slice times
    slicetimes = tide_io.getslicetimesfromfile(slicetimename)
    timings.append(['Slice times determined', time.time(), None, None])

    # normalize the input data
    normdata, demeandata = normalizevoxels(fmri_data, detrendorder, validvoxels, time, timings)
    normdata_byslice = normdata.reshape((xsize * ysize, numslices, timepoints))

    # read in estimation mask if present. Otherwise, make variance mask if selected, otherwise use intensity mask.
    infodict['estmaskname'] = estmaskname
    infodict['usevarmask'] = usevarmask
    infodict['varmaskthreshpct'] = varmaskthreshpct
    infodict['varmasktype'] = varmasktype
    infodict['varmaskbyslice'] = varmaskbyslice
    if debug:
        print(estmaskname, usevarmask, varmaskthreshpct, varmasktype)
    if estmaskname is not None:
        tide_util.logmem('before reading in estmask', file=memfile)
        estmask_byslice = readextmask(estmaskname, nim_hdr, xsize, ysize, numslices) * np.float64(mask_byslice)
        print('using estmask from file', estmaskname)
    else:
        # just fall back to the intensity mask
        estmask_byslice = mask_byslice.astype('float64')
        print('not using separate estimation mask')
    if usevarmask:
        # find the most variable voxels in each slice
        if varmasktype == 'std':
            var_byslice = np.std(normdata_byslice, axis=2)
        elif varmasktype == 'mad':
            var_byslice = mad(normdata_byslice, axis=2)
        tide_io.savetonifti(var_byslice.reshape((xsize, ysize, numslices)), theheader, outputroot + '_var')
        if varmaskbyslice:
            for theslice in range(numslices):
                estmask_byslice[:, theslice] *= tide_stats.makemask(var_byslice[:, theslice],
                                                                    threshpct=varmaskthreshpct,
                                                                    nozero=True).astype('float64')
        else:
            estmask_byslice *= tide_stats.makemask(var_byslice,
                                                   threshpct=varmaskthreshpct,
                                                   nozero=True).astype('float64')
        tide_io.savetonifti(estmask_byslice.reshape((xsize, ysize, numslices)), theheader,
                            outputroot + '_varmask')
        print('using variance estimation mask with threshold', varmaskthreshpct)

    # now get an estimate of the cardiac signal
    print('estimating cardiac signal from fmri data')
    tide_util.logmem('before cardiacfromimage', file=memfile)
    cardfromfmri_sliceres, respfromfmri_sliceres, \
    slicesamplerate, numsteps = physiofromimage(normdata_byslice, estmask_byslice, numslices, timepoints, tr,
                                                slicetimes, thecardbandfilter, therespbandfilter,
                                                madnorm=domadnorm,
                                                nprocs=nprocs,
                                                notchpct=notchpct,
                                                usemask=usemaskcardfromfmri,
                                                debug=debug,
                                                verbose=verbose)
    timings.append(['Cardiac signal generated from image data', time.time(), None, None])
    slicetimeaxis = sp.linspace(0.0, tr * timepoints, num=(timepoints * numsteps), endpoint=False)
    tide_io.writevec(cardfromfmri_sliceres, outputroot + '_cardfromfmri_sliceres.txt')
    # stash away a copy of the waveform if we need it later
    raw_cardfromfmri_sliceres = np.array(cardfromfmri_sliceres)

    # find bad points in cardiac from fmri
    thebadcardpts = findbadpts(cardfromfmri_sliceres, 'cardfromfmri_sliceres', outputroot, slicesamplerate, infodict)

    cardiacwaveform = np.array(cardfromfmri_sliceres)
    badpointlist = np.array(thebadcardpts)

    infodict['slicesamplerate'] = slicesamplerate
    infodict['numcardpts_sliceres'] = timepoints * numsteps
    infodict['numsteps'] = numsteps

    # find key components of cardiac waveform
    print('extracting harmonic components')
    if outputlevel > 0:
        tide_io.writevec(cardfromfmri_sliceres * (1.0 - thebadcardpts), outputroot + '_cardfromfmri_sliceres_censored.txt')
    peakfreq_bold = getcardcoeffs((1.0 - thebadcardpts) * cardiacwaveform, slicesamplerate,
                                  minhr=minhr, maxhr=maxhr, smoothlen=smoothlen, debug=debug)
    infodict['cardiacbpm_bold'] = np.round(peakfreq_bold * 60.0, 2)
    infodict['cardiacfreq_bold'] = peakfreq_bold
    timings.append(['Cardiac signal from image data analyzed', time.time(), None, None])

    # resample to standard frequency
    cardfromfmri_stdres = tide_math.madnormalize(tide_resample.arbresample(cardfromfmri_sliceres,
                                                                           slicesamplerate,
                                                                           stdfreq,
                                                                           decimate=True,
                                                                           debug=False))

    tide_io.writevec(cardfromfmri_stdres, outputroot + '_cardfromfmri_' + str(stdfreq) + 'Hz.txt')
    infodict['numcardpts_stdres'] = len(cardfromfmri_stdres)

    # normalize the signal to remove envelope effects
    filtcardfromfmri_stdres, normcardfromfmri_stdres, cardfromfmrienv_stdres = cleancardiac(stdfreq,
                                                                                            cardfromfmri_stdres,
                                                                                            cutoff=envcutoff,
                                                                                            nyquist=slicesamplerate / 2.0,
                                                                                            thresh=envthresh)
    tide_io.writevec(normcardfromfmri_stdres, outputroot + '_normcardfromfmri_' + str(stdfreq) + 'Hz.txt')
    tide_io.writevec(cardfromfmrienv_stdres, outputroot + '_cardfromfmrienv_' + str(stdfreq) + 'Hz.txt')

    # calculate quality metrics
    cardfromfmri_s_mean, cardfromfmri_s_std, cardfromfmri_s_waveform, \
    cardfromfmri_k_mean, cardfromfmri_k_std, cardfromfmri_k_waveform, \
    cardfromfmri_e_mean, cardfromfmri_e_std, cardfromfmri_e_waveform \
        = plethquality(normcardfromfmri_stdres, stdfreq)
    infodict['S_sqi_mean_bold'] = cardfromfmri_s_mean
    infodict['S_sqi_std_bold'] = cardfromfmri_s_std
    infodict['K_sqi_mean_bold'] = cardfromfmri_k_mean
    infodict['K_sqi_std_bold'] = cardfromfmri_k_std
    infodict['E_sqi_mean_bold'] = cardfromfmri_e_mean
    infodict['E_sqi_std_bold'] = cardfromfmri_e_std
    if outputlevel > 0:
        tide_io.writevec(cardfromfmri_s_waveform, outputroot + '_normcardfromfmri_S_sqi_' + str(stdfreq) + 'Hz.txt')
        tide_io.writevec(cardfromfmri_k_waveform, outputroot + '_normcardfromfmri_K_sqi_' + str(stdfreq) + 'Hz.txt')
        tide_io.writevec(cardfromfmri_e_waveform, outputroot + '_normcardfromfmri_E_sqi_' + str(stdfreq) + 'Hz.txt')

    thebadcardpts_stdres = findbadpts(cardfromfmri_stdres, 'cardfromfmri_' + str(stdfreq) + 'Hz', outputroot, stdfreq,
                                      infodict)

    timings.append(['Cardiac signal from image data resampled and saved', time.time(), None, None])

    # apply the deep learning filter if we're going to do that
    if dodlfilter:
        if dlfilterexists:
            if mpfix:
                print('performing super dangerous openmp workaround')
                os.environ['KMP_DUPLICATE_LIB_OK'] = "TRUE"
            modelpath = os.path.join(os.path.split(os.path.split(os.path.split(__file__)[0])[0])[0], 'rapidtide',
                                     'data',
                                     'models')
            thedlfilter = tide_dlfilt.dlfilter(modelpath=modelpath)
            thedlfilter.loadmodel(modelname)
            infodict['dlfiltermodel'] = modelname
            normdlfilteredcard = thedlfilter.apply(normcardfromfmri_stdres)
            tide_io.writevec(normdlfilteredcard, outputroot + '_normcardfromfmri_dlfiltered_' + str(stdfreq) + 'Hz.txt')
            dlfilteredcard = thedlfilter.apply(cardfromfmri_stdres)
            tide_io.writevec(dlfilteredcard, outputroot + '_cardfromfmri_dlfiltered_' + str(stdfreq) + 'Hz.txt')

            # calculate quality metrics
            dl_s_mean, dl_s_std, dl_s_waveform, \
            dl_k_mean, dl_k_std, dl_k_waveform, \
            dl_e_mean, dl_e_std, dl_e_waveform \
                = plethquality(dlfilteredcard, stdfreq)
            infodict['S_sqi_mean_dlfiltered'] = dl_s_mean
            infodict['S_sqi_std_dlfiltered'] = dl_s_std
            infodict['K_sqi_mean_dlfiltered'] = dl_k_mean
            infodict['K_sqi_std_dlfiltered'] = dl_k_std
            infodict['E_sqi_mean_dlfiltered'] = dl_e_mean
            infodict['E_sqi_std_dlfiltered'] = dl_e_std
            if outputlevel > 0:
                tide_io.writevec(dl_s_waveform,
                                 outputroot + '_normcardfromfmri_dlfiltered_S_sqi_' + str(stdfreq) + 'Hz.txt')
                tide_io.writevec(dl_k_waveform,
                                 outputroot + '_normcardfromfmri_dlfiltered_K_sqi_' + str(stdfreq) + 'Hz.txt')
                tide_io.writevec(dl_e_waveform,
                                 outputroot + '_normcardfromfmri_dlfiltered_E_sqi_' + str(stdfreq) + 'Hz.txt')

            # downsample to sliceres from stdres
            # cardfromfmri_sliceres = tide_math.madnormalize(
            #    tide_resample.arbresample(dlfilteredcard, stdfreq, slicesamplerate, decimate=True, debug=False))
            stdtimeaxis = (1.0 / stdfreq) * sp.linspace(0.0, len(dlfilteredcard), num=(len(dlfilteredcard)),
                                                        endpoint=False)
            arb_lowerstop = 0.0
            arb_lowerpass = 0.0
            arb_upperpass = slicesamplerate / 2.0
            arb_upperstop = slicesamplerate / 2.0
            theaafilter = tide_filt.noncausalfilter(filtertype='arb')
            theaafilter.setarb(arb_lowerstop, arb_lowerpass, arb_upperpass, arb_upperstop)

            cardfromfmri_sliceres = tide_math.madnormalize(
                tide_resample.doresample(stdtimeaxis,
                                         theaafilter.apply(stdfreq, dlfilteredcard),
                                         slicetimeaxis,
                                         method='univariate',
                                         padlen=0))
            tide_io.writevec(cardfromfmri_sliceres, outputroot + '_cardfromfmri_dlfiltered_sliceres.txt')
            infodict['used_dlreconstruction_filter'] = True
            peakfreq_dlfiltered = getcardcoeffs(cardfromfmri_sliceres, slicesamplerate,
                                                minhr=minhr, maxhr=maxhr, smoothlen=smoothlen, debug=debug)
            infodict['cardiacbpm_dlfiltered'] = np.round(peakfreq_dlfiltered * 60.0, 2)
            infodict['cardiacfreq_dlfiltered'] = peakfreq_dlfiltered

            # check the match between the raw and filtered cardiac signals
            maxval, maxdelay, failreason = checkcardmatch(raw_cardfromfmri_sliceres, cardfromfmri_sliceres, slicesamplerate,
                                              debug=debug)
            print('Filtered cardiac fmri waveform delay is', maxdelay, 'relative to raw fMRI data')
            print('Correlation coefficient between cardiac regressors:', maxval)
            infodict['corrcoeff_raw2filt'] = maxval + 0
            infodict['delay_raw2filt'] = maxdelay + 0
            infodict['failreason_raw2filt'] = failreason + 0

            timings.append(['Deep learning filter applied', time.time(), None, None])
        else:
            print('dlfilter could not be loaded - skipping')

    # get the cardiac signal from a file, if specified
    if cardiacfilename is not None:
        tide_util.logmem('before cardiacfromfile', file=memfile)
        pleth_sliceres, pleth_stdres = getphysiofile(cardiacfilename, colnum, colname,
                                                     inputfreq, inputstart, slicetimeaxis, stdfreq,
                                                     envcutoff, envthresh,
                                                     timings, infodict, outputroot,
                                                     outputlevel=outputlevel,
                                                     debug=False)

        if dodlfilter and dlfilterexists:
            maxval, maxdelay, failreason = checkcardmatch(pleth_sliceres, cardfromfmri_sliceres, slicesamplerate, debug=debug)
            print('Input cardiac waveform delay is', maxdelay, 'relative to filtered fMRI data')
            print('Correlation coefficient between cardiac regressors:', maxval)
            infodict['corrcoeff_filt2pleth'] = maxval + 0
            infodict['delay_filt2pleth'] = maxdelay + 0
            infodict['failreason_filt2pleth'] = failreason + 0

        # check the match between the bold and physio cardiac signals
        maxval, maxdelay, failreason = checkcardmatch(pleth_sliceres, raw_cardfromfmri_sliceres, slicesamplerate, debug=debug)
        print('Input cardiac waveform delay is', maxdelay, 'relative to fMRI data')
        print('Correlation coefficient between cardiac regressors:', maxval)
        infodict['corrcoeff_raw2pleth'] = maxval + 0
        infodict['delay_raw2pleth'] = maxdelay + 0
        infodict['failreason_raw2pleth'] = failreason + 0

        # align the pleth signal with the cardiac signal derived from the data
        if aligncardiac:
            alignpts_sliceres = -maxdelay / slicesamplerate  # maxdelay is in seconds
            pleth_sliceres, dummy1, dummy2, dummy2 = tide_resample.timeshift(pleth_sliceres, alignpts_sliceres,
                                                                             int(10.0 * slicesamplerate))
            alignpts_stdres = -maxdelay * stdfreq  # maxdelay is in seconds
            pleth_stdres, dummy1, dummy2, dummy3 = tide_resample.timeshift(pleth_stdres, alignpts_stdres,
                                                                           int(10.0 * stdfreq))
        tide_io.writevec(pleth_sliceres, outputroot + '_pleth_sliceres.txt')
        tide_io.writevec(pleth_stdres, outputroot + '_pleth_' + str(stdfreq) + 'Hz.txt')

        # now clean up cardiac signal
        filtpleth_stdres, normpleth_stdres, plethenv_stdres = cleancardiac(stdfreq, pleth_stdres, cutoff=envcutoff,
                                                                           thresh=envthresh)
        tide_io.writevec(normpleth_stdres, outputroot + '_normpleth_' + str(stdfreq) + 'Hz.txt')
        if outputlevel > 0:
            tide_io.writevec(plethenv_stdres, outputroot + '_plethenv_' + str(stdfreq) + 'Hz.txt')

        # calculate quality metrics
        s_mean, s_std, s_waveform, \
        k_mean, k_std, k_waveform, \
        e_mean, e_std, e_waveform \
            = plethquality(filtpleth_stdres, stdfreq)
        infodict['S_sqi_mean_pleth'] = s_mean
        infodict['S_sqi_std_pleth'] = s_std
        infodict['K_sqi_mean_pleth'] = k_mean
        infodict['K_sqi_std_pleth'] = k_std
        infodict['E_sqi_mean_pleth'] = e_mean
        infodict['E_sqi_std_pleth'] = e_std
        if outputlevel > 0:
            tide_io.writevec(s_waveform, outputroot + '_normpleth_S_sqi_' + str(stdfreq) + 'Hz.txt')
            tide_io.writevec(k_waveform, outputroot + '_normpleth_K_sqi_' + str(stdfreq) + 'Hz.txt')
            tide_io.writevec(e_waveform, outputroot + '_normpleth_E_sqi_' + str(stdfreq) + 'Hz.txt')

        if dodlfilter and dlfilterexists:
            dlfilteredpleth = thedlfilter.apply(pleth_stdres)
            tide_io.writevec(dlfilteredpleth, outputroot + '_pleth_dlfiltered_' + str(stdfreq) + 'Hz.txt')
            maxval, maxdelay, failreason = checkcardmatch(pleth_stdres, dlfilteredpleth, stdfreq, debug=debug)
            print('Filtered pleth cardiac waveform delay is', maxdelay, 'relative to raw pleth data')
            print('Correlation coefficient between pleth regressors:', maxval)
            infodict['corrcoeff_pleth2filtpleth'] = maxval + 0
            infodict['delay_pleth2filtpleth'] = maxdelay + 0
            infodict['failreason_pleth2filtpleth'] = failreason + 0

        # find bad points in plethysmogram
        thebadplethpts_sliceres = findbadpts(pleth_sliceres, 'pleth_sliceres', outputroot, slicesamplerate, infodict,
                                             thetype='fracval')

        thebadplethpts_stdres = findbadpts(pleth_stdres, 'pleth_' + str(stdfreq) + 'Hz', outputroot, stdfreq, infodict,
                                           thetype='fracval')
        timings.append(['Cardiac signal from physiology data resampled to standard and saved', time.time(), None, None])

        # find key components of cardiac waveform
        filtpleth = tide_math.madnormalize(thecardbandfilter.apply(slicesamplerate, pleth_sliceres))
        peakfreq_file = getcardcoeffs((1.0 - thebadplethpts_sliceres) * filtpleth, slicesamplerate,
                                      minhr=minhr, maxhr=maxhr, smoothlen=smoothlen, debug=debug)
        timings.append(['Cardiac coefficients calculated from pleth waveform', time.time(), None, None])
        infodict['cardiacbpm_pleth'] = np.round(peakfreq_file * 60.0, 2)
        infodict['cardiacfreq_pleth'] = peakfreq_file
        timings.append(['Cardiac signal from physiology data analyzed', time.time(), None, None])
        timings.append(['Cardiac parameters extracted from physiology data', time.time(), None, None])

        if not projectwithraw:
            cardiacwaveform = np.array(pleth_sliceres)
            badpointlist = 1.0 - (1.0 - thebadplethpts_sliceres) * (1.0 - badpointlist)

        if doplot:
            figure()
            plot(slicetimeaxis, pleth_sliceres, 'r', slicetimeaxis, cardfromfmri_sliceres, 'b')
            show()
        infodict['pleth'] = True
        peakfreq = peakfreq_file
    else:
        infodict['pleth'] = False
        peakfreq = peakfreq_bold
    if outputlevel > 0:
        tide_io.writevec(badpointlist, outputroot + '_overall_sliceres_badpts.txt')

    #  extract the fundamental
    if forcedhr is not None:
        peakfreq = forcedhr
        infodict['forcedhr'] = peakfreq
    if cardiacfilename is None:
        filthiresfund = tide_math.madnormalize(getfundamental(cardiacwaveform * (1.0 - thebadcardpts),
                                                              slicesamplerate,
                                                              peakfreq))
    else:
        filthiresfund = tide_math.madnormalize(getfundamental(cardiacwaveform,
                                                              slicesamplerate,
                                                              peakfreq))
    if outputlevel > 0:
        tide_io.writevec(filthiresfund, outputroot + '_cardiacfundamental.txt')

    # now calculate the phase waveform
    tide_util.logmem('before analytic phase analysis', file=memfile)
    instantaneous_phase, amplitude_envelope = tide_fit.phaseanalysis(filthiresfund)
    if outputlevel > 0:
        tide_io.writevec(amplitude_envelope, outputroot + '_ampenv.txt')
        tide_io.writevec(instantaneous_phase, outputroot + '_instphase_unwrapped.txt')

    if filtphase:
        print('filtering phase waveform')
        instantaneous_phase = tide_math.trendfilt(instantaneous_phase, debug=False)
        if outputlevel > 0:
            tide_io.writevec(instantaneous_phase, outputroot + '_filtered_instphase_unwrapped.txt')
    initialphase = instantaneous_phase[0]
    infodict['phi0'] = initialphase
    timings.append(['Phase waveform generated', time.time(), None, None])

    # account for slice time offests
    offsets_byslice = np.zeros((xsize * ysize, numslices), dtype=np.float64)
    for i in range(numslices):
        offsets_byslice[:, i] = slicetimes[i]

    # remap offsets to space by time
    fmri_offsets = offsets_byslice.reshape(numspatiallocs)

    # save the information file
    if saveinfoasjson:
        tide_io.writedicttojson(infodict, outputroot + '_info.json')
    else:
        tide_io.writedict(infodict, outputroot + '_info.txt')

    # interpolate the instantaneous phase
    upsampledslicetimeaxis = sp.linspace(0.0, tr * timepoints, num=(timepoints * numsteps * upsamplefac),
                                         endpoint=False)
    interpphase = tide_math.phasemod(
        tide_resample.doresample(slicetimeaxis, instantaneous_phase, upsampledslicetimeaxis,
                                 method='univariate', padlen=0),
        centric=centric)
    if outputlevel > 0:
        tide_io.writevec(interpphase, outputroot + '_interpinstphase.txt')

    if cardcalconly:
        print('cardiac waveform calculations done - exiting')
        # Process and save timing information
        nodeline = 'Processed on ' + platform.node()
        tide_util.proctiminginfo(timings, outputfile=outputroot + '_runtimings.txt', extraheader=nodeline)
        tide_util.logmem('final', file=memfile)
        sys.exit()

    # find the phase values for all timepoints in all slices
    phasevals = np.zeros((numslices, timepoints), dtype=np.float64)
    for theslice in range(numslices):
        thetimes = sp.linspace(0.0, tr * timepoints, num=timepoints, endpoint=False) + slicetimes[theslice]
        phasevals[theslice, :] = tide_math.phasemod(
            tide_resample.doresample(slicetimeaxis, instantaneous_phase, thetimes, method='univariate', padlen=0),
            centric=centric)
        if debug:
            tide_io.writevec(thetimes, outputroot + '_times_' + str(theslice).zfill(2) + '.txt')
            tide_io.writevec(phasevals[theslice, :], outputroot + '_phasevals_' + str(theslice).zfill(2) + '.txt')
    timings.append(['Slice phases determined for all timepoints', time.time(), None, None])

    # construct a destination array
    tide_util.logmem('before making destination arrays', file=memfile)
    app = np.zeros((xsize, ysize, numslices, destpoints), dtype=np.float64)
    app_byslice = app.reshape((xsize * ysize, numslices, destpoints))
    rawapp = np.zeros((xsize, ysize, numslices, destpoints), dtype=np.float64)
    rawapp_byslice = rawapp.reshape((xsize * ysize, numslices, destpoints))
    rawapp_bypoint = np.zeros(destpoints, dtype=np.float64)
    weights = np.zeros((xsize, ysize, numslices, destpoints), dtype=np.float64)
    weight_byslice = weights.reshape((xsize * ysize, numslices, destpoints))
    weight_bypoint = np.zeros(destpoints, dtype=np.float64)
    timings.append(['Output arrays allocated', time.time(), None, None])

    if centric:
        outphases = sp.linspace(-np.pi, np.pi, num=destpoints, endpoint=False)
    else:
        outphases = sp.linspace(0.0, 2.0 * np.pi, num=destpoints, endpoint=False)
    phasestep = outphases[1] - outphases[0]
    congridwidth = congridbins * phasestep

    #######################################################################################################
    #
    # now do the phase projection
    #
    #
    if fmrimod == 'demean':
        fmri_data_byslice = demeandata.reshape((xsize * ysize, numslices, timepoints))
    else:
        fmri_data_byslice = fmri_data.reshape((xsize * ysize, numslices, timepoints))

    timings.append(['Phase projection to image started', time.time(), None, None])
    print('starting phase projection')
    proclist = range(timepoints)       # proclist is the list of all timepoints to be projected
    if censorbadpts:
        censorlist = np.zeros(timepoints, dtype='int')
        censorlist[np.where(badpointlist > 0.0)[0] // numsteps] = 1
        proclist = np.where(censorlist < 1)[0]

    for t in proclist:
        thevals, theweights, theindices = tide_resample.congrid(outphases,
                                                                tide_math.phasemod(instantaneous_phase[t],
                                                                                   centric=centric),
                                                                1.0,
                                                                congridbins,
                                                                kernel=gridkernel,
                                                                cyclic=True)
        for i in range(len(theindices)):
            weight_bypoint[theindices[i]] += theweights[i]
            rawapp_bypoint[theindices[i]] += theweights[i] * cardfromfmri_sliceres[t]
    rawapp_bypoint = np.nan_to_num(rawapp_bypoint / weight_bypoint)
    app_bypoint = rawapp_bypoint - np.min(rawapp_bypoint)
    tide_io.writevec(app_bypoint, outputroot + '_cardcyclefromfmri.txt')

    if not verbose:
        print('phase projecting...')

    # make a lowpass filter for the projected data. Limit frequency to 3 cycles per 2pi (1/6th Fs)
    phaseFs = 1.0 / phasestep
    phaseFc = phaseFs / 6.0
    appsmoothingfilter = tide_filt.noncausalfilter('arb', cyclic=True, padtime=0.0)
    appsmoothingfilter.setarb(0.0, 0.0, phaseFc, phaseFc)
    for theslice in range(numslices):
        if verbose:
            print('phase projecting for slice', theslice)
        validlocs = np.where(projmask_byslice[:, theslice] > 0)[0]
        indexlist = range(0, len(phasevals[theslice, :]))
        if len(validlocs) > 0:
            for t in proclist:
                filteredmr = -fmri_data_byslice[validlocs, theslice, t]
                thevals, theweights, theindices = tide_resample.congrid(outphases,
                                                                        phasevals[theslice, t],
                                                                        1.0,
                                                                        congridbins,
                                                                        kernel=gridkernel,
                                                                        cyclic=True)
                for i in range(len(theindices)):
                    weight_byslice[validlocs, theslice, theindices[i]] += theweights[i]
                    rawapp_byslice[validlocs, theslice, theindices[i]] += theweights[i] * filteredmr
            for d in range(destpoints):
                if weight_byslice[validlocs[0], theslice, d] == 0.0:
                    weight_byslice[validlocs, theslice, d] = 1.0
            rawapp_byslice[validlocs, theslice, :] = \
                np.nan_to_num(rawapp_byslice[validlocs, theslice, :] / weight_byslice[validlocs, theslice, :])
        else:
            rawapp_byslice[:, theslice, :] = 0.0

        # smooth the projected data along the time dimension
        if smoothapp:
            for loc in validlocs:
                rawapp_byslice[loc, theslice, :] = appsmoothingfilter.apply(phaseFs, rawapp_byslice[loc, theslice, :])
        slicemin = np.min(rawapp_byslice[validlocs, theslice, :], axis=1).reshape((-1, 1))
        app_byslice[validlocs, theslice, :] = rawapp_byslice[validlocs, theslice, :] - slicemin
    if not verbose:
        print('done')
    timings.append(['Phase projection to image completed', time.time(), None, None])
    print('phase projection done')

    # save the analytic phase projection image
    theheader = nim_hdr
    theheader['dim'][4] = destpoints
    theheader['toffset'] = -np.pi
    theheader['pixdim'][4] = 2.0 * np.pi / destpoints
    tide_io.savetonifti(app, theheader, outputroot + '_app')
    if outputlevel > 0:
        tide_io.savetonifti(rawapp, theheader, outputroot + '_rawapp')
    timings.append(['Phase projected data saved', time.time(), None, None])

    # make and save a voxel intensity histogram
    app2d = app.reshape((numspatiallocs, destpoints))
    validlocs = np.where(mask > 0)[0]
    histinput = app2d[validlocs, :].reshape((len(validlocs), destpoints))
    if outputlevel > 0:
        tide_stats.makeandsavehistogram(histinput, histlen, 0, outputroot + '_histogram')

    # find vessel threshholds
    tide_util.logmem('before making vessel masks', file=memfile)
    hardvesselthresh = tide_stats.getfracvals(np.max(histinput, axis=1), [0.98])[0] / 2.0
    softvesselthresh = softvesselfrac * hardvesselthresh
    print('hard, soft vessel threshholds set to', hardvesselthresh, softvesselthresh)

    # save a vessel masked version of app
    vesselmask = np.where(np.max(app, axis=3) > softvesselthresh, 1, 0)
    maskedapp2d = np.array(app2d)
    maskedapp2d[np.where(vesselmask.reshape(numspatiallocs) == 0)[0], :] = 0.0
    if outputlevel > 0:
        tide_io.savetonifti(maskedapp2d.reshape((xsize, ysize, numslices, destpoints)), theheader,
                            outputroot + '_maskedapp')
    del maskedapp2d
    timings.append(['Vessel masked phase projected data saved', time.time(), None, None])

    # save multiple versions of the hard vessel mask
    vesselmask = np.where(np.max(app, axis=3) > hardvesselthresh, 1, 0)
    '''meanval = np.mean(app, axis=3)
    medianval = np.median(app, axis=3)
    maxval = np.max(app, axis=3)
    directionality = (meanval - maxval / 2.0)
    direction = np.where(directionality < 0.0, -1, 1)'''
    minphase = np.argmin(app, axis=3) * 2.0 * np.pi / destpoints - np.pi
    maxphase = np.argmax(app, axis=3) * 2.0 * np.pi / destpoints - np.pi
    risediff = (maxphase - minphase) * vesselmask
    arteries = np.where(risediff < 0, 1, 0)
    veins = np.where(risediff > 0, 1, 0)
    '''arteries = np.where(direction < 0, 1, 0) * vesselmask
    veins = np.where(direction > 0, 1, 0) * vesselmask'''
    theheader = nim_hdr
    theheader['dim'][4] = 1
    tide_io.savetonifti(vesselmask, theheader, outputroot + '_vesselmask')
    if outputlevel > 0:
        tide_io.savetonifti(minphase, theheader, outputroot + '_minphase')
        tide_io.savetonifti(maxphase, theheader, outputroot + '_maxphase')
    tide_io.savetonifti(arteries, theheader, outputroot + '_arteries')
    tide_io.savetonifti(veins, theheader, outputroot + '_veins')
    #tide_io.savetonifti(directionality, theheader, outputroot + '_directionality')
    timings.append(['Masks saved', time.time(), None, None])

    # save a vessel image
    vesselmap = np.max(app, axis=3)
    tide_io.savetonifti(vesselmap, theheader, outputroot + '_vesselmap')

    # now generate aliased cardiac signals and regress them out of the data
    if doglm:
        # generate the signals
        timings.append(['Cardiac signal regression started', time.time(), None, None])
        tide_util.logmem('before cardiac regression', file=memfile)
        print('generating cardiac regressors')
        cardiacnoise = fmri_data * 0.0
        cardiacnoise_byslice = cardiacnoise.reshape((xsize * ysize, numslices, timepoints))
        phaseindices = (cardiacnoise * 0.0).astype(np.int16)
        phaseindices_byslice = phaseindices.reshape((xsize * ysize, numslices, timepoints))
        for theslice in range(numslices):
            print('calculating cardiac noise for slice', theslice)
            validlocs = np.where(projmask_byslice[:, theslice] > 0)[0]
            for t in range(timepoints):
                phaseindices_byslice[validlocs, theslice, t] = \
                    tide_util.valtoindex(outphases, phasevals[theslice, t])
                cardiacnoise_byslice[validlocs, theslice, t] = \
                    rawapp_byslice[validlocs, theslice, phaseindices_byslice[validlocs, theslice, t]]
        theheader = nim_hdr
        timings.append(['Cardiac signal generated', time.time(), None, None])
        if savecardiacnoise:
            tide_io.savetonifti(cardiacnoise.reshape((xsize, ysize, numslices, timepoints)), theheader,
                                outputroot + '_cardiacnoise')
            tide_io.savetonifti(phaseindices.reshape((xsize, ysize, numslices, timepoints)), theheader,
                                outputroot + '_phaseindices')
            timings.append(['Cardiac signal saved', time.time(), None, None])

        # now remove them
        tide_util.logmem('before cardiac removal', file=memfile)
        print('removing cardiac signal with GLM')
        filtereddata = 0.0 * fmri_data
        datatoremove = 0.0 * fmri_data
        validlocs = np.where(mask > 0)[0]
        numvalidspatiallocs = len(validlocs)
        threshval = 0.0
        if spatialglmdenoise:
            meanvals = np.zeros(timepoints, dtype=np.float64)
            rvals = np.zeros(timepoints, dtype=np.float64)
            r2vals = np.zeros(timepoints, dtype=np.float64)
            fitcoffs = np.zeros(timepoints, dtype=np.float64)
            fitNorm = np.zeros(timepoints, dtype=np.float64)
            print('running glm on', timepoints, 'timepoints')
            tide_glmpass.glmpass(timepoints,
                                 fmri_data[validlocs, :],
                                 threshval,
                                 cardiacnoise[validlocs, :],
                                 meanvals,
                                 rvals,
                                 r2vals,
                                 fitcoffs,
                                 fitNorm,
                                 datatoremove[validlocs, :],
                                 filtereddata[validlocs, :],
                                 reportstep=(timepoints // 100),
                                 mp_chunksize=10,
                                 procbyvoxel=False,
                                 nprocs=nprocs
                                 )
            datatoremove[validlocs, :] = np.multiply(cardiacnoise[validlocs, :], fitcoffs[None, :])
            filtereddata = fmri_data - datatoremove
            timings.append(['Cardiac signal regression finished', time.time(), timepoints, 'timepoints'])
            tide_io.writevec(fitcoffs, outputroot + '_fitcoff.txt')
            tide_io.writevec(meanvals, outputroot + '_fitmean.txt')
            tide_io.writevec(rvals, outputroot + '_fitR.txt')
        else:
            meanvals = np.zeros(numspatiallocs, dtype=np.float64)
            rvals = np.zeros(numspatiallocs, dtype=np.float64)
            r2vals = np.zeros(numspatiallocs, dtype=np.float64)
            fitcoffs = np.zeros(numspatiallocs, dtype=np.float64)
            fitNorm = np.zeros(numspatiallocs, dtype=np.float64)
            print('running glm on', numvalidspatiallocs, 'voxels')
            tide_glmpass.glmpass(numvalidspatiallocs,
                                 fmri_data[validlocs, :],
                                 threshval,
                                 cardiacnoise[validlocs, :],
                                 meanvals[validlocs],
                                 rvals[validlocs],
                                 r2vals[validlocs],
                                 fitcoffs[validlocs],
                                 fitNorm[validlocs],
                                 datatoremove[validlocs, :],
                                 filtereddata[validlocs, :],
                                 procbyvoxel=True,
                                 nprocs=nprocs
                                 )
            timings.append(['Cardiac signal regression finished', time.time(), numspatiallocs, 'voxels'])
            theheader = nim_hdr
            theheader['dim'][4] = 1
            tide_io.savetonifti(fitcoffs.reshape((xsize, ysize, numslices)), theheader,
                                outputroot + '_fitamp')
            tide_io.savetonifti(meanvals.reshape((xsize, ysize, numslices)), theheader,
                                outputroot + '_fitamp')
            tide_io.savetonifti(rvals.reshape((xsize, ysize, numslices)), theheader,
                                outputroot + '_fitR')

        theheader = nim_hdr
        tide_io.savetonifti(filtereddata.reshape((xsize, ysize, numslices, timepoints)), theheader,
                            outputroot + '_filtereddata')
        tide_io.savetonifti(datatoremove.reshape((xsize, ysize, numslices, timepoints)), theheader,
                            outputroot + '_datatoremove')
        timings.append(['Cardiac signal regression files written', time.time(), None, None])

    timings.append(['Done', time.time(), None, None])

    # Process and save timing information
    nodeline = 'Processed on ' + platform.node()
    tide_util.proctiminginfo(timings, outputfile=outputroot + '_runtimings.txt', extraheader=nodeline)

    tide_util.logmem('final', file=memfile)


if __name__ == '__main__':

    # grab the command line arguments then pass them off.
    nargs = len(sys.argv)
    if nargs < 4:
        usage()
        exit()

    happy_main(sys.argv)