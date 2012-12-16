"""Assorted functions for statistical calculations."""
from __future__ import division
import numpy as np
import scipy as sp
from scipy import stats
import statsmodels.api as sm


def bootstrap(*args, **kwargs):
    """Resample one or more arrays and call a function on each sample.

    Positional arguments are a sequence of arrays to bootrap
    along the first axis and pass to a summary function.

    Keyword arguments:
        n_boot : int
            number of iterations
        axis : int
            will pass axis to ``func``
        smooth : bool
            if True, performs a smoothed bootstrap
            (draws samples from a kernel destiny estimate)
            only works for one-dimensional inputs
        func : callable
            function to call on the args that are passed in

    Returns
    -------
    boot_dist: array
        array of bootstrapped statistic values

    """
    # Ensure list of arrays are same length
    if len(np.unique(map(len, args))) > 1:
        raise ValueError("All input arrays must have the same length")
    n = len(args[0])

    # Default keyword arguments
    n_boot = kwargs.get("n_boot", 10000)
    func = kwargs.get("func", np.mean)
    axis = kwargs.get("axis", None)
    smooth = kwargs.get("smooth", False)
    if axis is None:
        func_kwargs = dict()
    else:
        func_kwargs = dict(axis=axis)

    # Do the bootstrap
    boot_dist = []
    if smooth:
        kde = [stats.gaussian_kde(a) for a in args]
    for i in xrange(int(n_boot)):
        resampler = np.random.randint(0, n, n)
        if smooth:
            sample = [a.resample(n) for a in kde]
        else:
            sample = [a[resampler] for a in args]
        boot_dist.append(func(*sample, **func_kwargs))
    return np.array(boot_dist)


def percentiles(a, pcts, axis=None):
    """Like scoreatpercentile but can take and return array of percentiles.

    Parameters
    ----------
    a : array
        data
    pcts : sequence of percentile values
        percentile or percentiles to find score at
    axis : int or None
        if not None, computes scores over this axis

    Returns
    -------
    scores: array
        array of scores at requested percentiles
        first dimension is length of object passed to ``pcts``

    """
    scores = []
    try:
        n = len(pcts)
    except TypeError:
        pcts = [pcts]
        n = 0
    for i, p in enumerate(pcts):
        if axis is None:
            score = stats.scoreatpercentile(a.ravel(), p)
        else:
            score = np.apply_along_axis(stats.scoreatpercentile, axis, a, p)
        scores.append(score)
    scores = np.asarray(scores)
    if not n:
        scores = scores.squeeze()
    return scores


def add_constant(a):
    """Add a constant term to a design matrix.

    Parameters
    ----------
    a : array
        original design matrix

    Returns
    -------
    a : array
        design matrix with constant as final column

    """
    return np.column_stack((a, np.ones(len(a))))


def fsl_highpass_matrix(n_tp, cutoff, tr=1):
    """Return a matrix to implement FSL's gaussian running line filter.

    This returns a matrix that you premultiply your data with to
    implement the filter.

    Parameters
    ----------
    n_tp : int
        number of observations in data
    cutoff : float
        filter cutoff in seconds
    tr : float
        TR of data in seconds

    Return
    ------
    F : n_tp square array
        filter matrix

    """
    cutoff = cutoff / tr
    sig2n = np.square(cutoff / np.sqrt(2))

    kernel = np.exp(-np.square(np.arange(n_tp)) / (2 * sig2n))
    kernel = 1 / np.sqrt(2 * np.pi * sig2n) * kernel

    K = sp.linalg.toeplitz(kernel)
    K = np.dot(np.diag(1 / K.sum(axis=1)), K)

    H = np.zeros((n_tp, n_tp))
    X = np.column_stack((np.ones(n_tp), np.arange(n_tp)))
    for k in xrange(n_tp):
        W = np.diag(K[k])
        hat = np.dot(np.dot(X, np.linalg.pinv(np.dot(W, X))), W)
        H[k] = hat[k]
    F = np.eye(n_tp) - H
    return F


def fsl_highpass_filter(data, cutoff, tr=1, copy=True):
    """Highpass filter data with gaussian running line filter.

    Parameters
    ----------
    data : 1d or 2d array
        data array where first dimension is observations
    cutoff : float
        filter cutoff in seconds
    tr : float
        data TR in seconds
    copy : boolean
        if False data is filtered in place

    Returns
    -------
    data : 1d or 2d array
        filtered version of the data

    """
    if copy:
        data = data.copy()
    # Ensure data is in right shape
    n_tp = len(data)
    data = np.atleast_2d(data).reshape(n_tp, -1)

    # Filter each column of the data
    F = fsl_highpass_matrix(n_tp, cutoff, tr)
    data[:] = np.dot(F, data)

    return data.squeeze()


def randomize_onesample(a, n_iter=10000, random_seed=None, return_dist=False):
    """Nonparametric one-sample T test through randomization.

    On each iteration, randomly flip the signs of the values in ``a``
    and test the mean against 0.

    Parameters
    ----------
    a : sequence
        input data
    n_iter : int
        number of randomization iterations
    random_seed : int or None
        seed to use for random number generator
    return_dist : bool
        if True will return the distribution of means

    Returns
    -------
    obs_t : float
        group mean T statistic
    obs_p : float
        one-tailed p value that the population mean is greater than 0
        (1 - the percentile of the observed mean in the null dist)
    dist : ndarray, optional
        if return_dist is True, this will return the full null distribution

    """
    a = np.asarray(a)
    n_samp = len(a)

    rs = np.random.RandomState(random_seed)
    flipper = (rs.uniform(size=(n_samp, n_iter)) > 0.5) * 2 - 1
    rand_dist = a[:, None] * flipper

    err_denom = np.sqrt(n_samp - 1)
    std_err = rand_dist.std(axis=0) / err_denom
    t_dist = rand_dist.mean(axis=0) / std_err

    obs_t = a.mean() / (a.std() / err_denom)
    cdf = sm.distributions.ECDF(t_dist)
    obs_p = 1 - cdf(obs_t)

    if return_dist:
        return obs_t, obs_p, t_dist
    return obs_t, obs_p


def randomize_corrmat(a, tail="both", corrected=True, n_iter=1000,
                      random_seed=None, return_dist=False):
    """Test the significance of set of correlations with permutations.

    By default this corrects for multiple comparisons across one side
    of the matrix.

    Parameters
    ----------
    a : n_vars x n_obs array
        array with variables as rows
    tail : both | upper | lower
        whether test should be two-tailed, or which tail to integrate over
    corrected : boolean
        if True reports p values with respect to the max stat distribution
    n_iter : int
        number of permutation iterations
    random_seed : int or None
        seed for RNG
    return_dist : bool
        if True, return n_vars x n_vars x n_iter

    Returns
    -------
    p_mat : float
        array of probabilites for actual correlation from null CDF

    """
    if tail not in ["upper", "lower", "both"]:
        raise ValueError("'tail' must be 'upper', 'lower', or 'both'")

    rs = np.random.RandomState(random_seed)

    a = np.asarray(a)
    flat_a = a.ravel()
    n_vars, n_obs = a.shape

    # Do the permutations to establish a null distribution
    null_dist = np.empty((n_vars, n_vars, n_iter))
    for i_i in xrange(n_iter):
        perm_i = np.concatenate([rs.permutation(n_obs) + (v * n_obs)
                                 for v in range(n_vars)])
        a_i = flat_a[perm_i].reshape(n_vars, n_obs)
        null_dist[..., i_i] = np.corrcoef(a_i)

    # Get the observed correlation values
    real_corr = np.corrcoef(a)

    # Figure out p values based on the permutation distribution
    p_mat = np.zeros((n_vars, n_vars))
    upper_tri = np.triu_indices(n_vars, 1)

    if corrected:
        if tail == "both":
            max_dist = np.abs(null_dist[upper_tri]).max(axis=0)
        elif tail == "lower":
            max_dist = null_dist[upper_tri].min(axis=0)
        elif tail == "upper":
            max_dist = null_dist[upper_tri].max(axis=0)

        cdf = sm.distributions.ECDF(max_dist)

        for i, j in zip(*upper_tri):
            observed = real_corr[i, j]
            if tail == "both":
                p_ij = 1 - cdf(abs(observed))
            elif tail == "lower":
                p_ij = cdf(observed)
            elif tail == "upper":
                p_ij = 1 - cdf(observed)
            p_mat[i, j] = p_ij

    else:
        for i, j in zip(*upper_tri):

            null_corrs = null_dist[i, j]
            cdf = sm.distributions.ECDF(null_corrs)

            observed = real_corr[i, j]
            if tail == "both":
                p_ij = 2 * (1 - cdf(abs(observed)))
            elif tail == "lower":
                p_ij = cdf(observed)
            elif tail == "upper":
                p_ij = 1 - cdf(observed)
            p_mat[i, j] = p_ij

    # Make p matrix symettrical with nans on the diagonal
    p_mat += p_mat.T
    p_mat[np.diag_indices(n_vars)] = np.nan

    if return_dist:
        return p_mat, null_dist
    return p_mat
