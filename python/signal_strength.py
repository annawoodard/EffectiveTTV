from collections import defaultdict
import os

import numpy as np
from numpy.polynomial import Polynomial

# TODO only run this once
# TODO do this with roofit instead of numpy, for simpler PhysicsModel

def load(config):
    x = {}
    y = {}

    fn = os.path.join(config['outdir'], 'cross_sections.npy')
    for process, info in np.load(fn)[()].items():
        coefficients = info['coefficients']
        cross_section = info['cross section']
        sm_coefficients = np.array([tuple([0.0] * len(coefficients.dtype))], dtype=coefficients.dtype)
        sm_cross_section = np.mean(cross_section[coefficients == sm_coefficients])

        x[process] = {'sm': 0}
        y[process] = {'sm': sm_cross_section}

        for operator in coefficients.dtype.names:
            x[process][operator] = np.concatenate([coefficients[operator][coefficients[operator] != 0], np.array([0.0])])
            y[process][operator] = np.concatenate([cross_section[coefficients[operator] != 0], np.array([sm_cross_section], dtype=cross_section.dtype)])

    return x, y

def load_mus(config):
    mus = defaultdict(dict)
    coefficients, cross_sections = load(config)

    # for process in coefficients:
    #     print 'process test is ', process
    for process in ['ttH', 'ttZ', 'ttW']:
    # for process in ['DY', 'H', 'WWW', 'WWZ', 'WZ', 'WZZ', 'ZZ', 'WW', 'ZZZ', 'tZq', 'tt', 'ttH', 'ttW', 'ttZ']:
    # for process in ['DY', 'H', 'WWW', 'WWZ', 'WZ', 'WZZ', 'ZZ', 'WW', 'ZZZ', 'tZq', 'tt', 'ttH', 'ttW', 'ttZ', 'tttt', 'tWZ']:
        # for operator in coefficients[process]:
        for operator in ['cHu', 'cu', 'cuW', 'cuB']:
        # for operator in coefficients[process]:
            if operator == 'sm':
                continue
            x = coefficients[process][operator]
            y = cross_sections[process][operator] / cross_sections[process]['sm']
            # mu=1 when coefficient=0, make sure the fit goes through that point
            weights = [1 if (i != 1) else 100000000 for i in y]

            try:
                # mus[operator][process] = Polynomial.fit(x, y, 2, w=weights)
                # mus[operator][process] = Polynomial.fit(x, y, 2)
                mus[operator][process] = Polynomial.fit(x, y, 2, w=weights, window=[min(x), max(x)])

                print 'x ', x
                print 'y ', y
                print operator, process
                # mus[operator][process] = np.polyfit(x, y, 2)
                print 'fit is ', mus[operator][process]
            except:
                print 'problem with ', operator, process
                print 'x is ', x
                print 'y is ', y

            print 'mu operator process ', operator, process, mus[operator].keys()

            # if mus[operator][process](1.) / mus[operator][process](0.) <= (1 + np.std(y)):
            #     # We can't tell the difference between this and a straight line, let's keep things simple
            #     mus[operator][process].coef = (1., 0., 0.)

    # print 'mus are ', mus
    return mus

def dump_mus(config):
    mus = load_mus(config)

    np.save(os.path.join(config['outdir'], 'mus.npy'), mus)
