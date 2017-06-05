
import glob
import logging
import itertools
import numpy as np
import os
import re
import shlex
import shutil
import subprocess
import stat
import yaml

from EffectiveTTV.EffectiveTTV.parameters import kappa
from EffectiveTTV.EffectiveTTV.signal_strength import dump_mus

def make(args, config):
    # Makeflow is a bit picky about whitespace
    frag = """\n{out}: {ins}\n\t{cmd}\n"""

    wrap = """#!/bin/sh

    source /cvmfs/cms.cern.ch/cmsset_default.sh
    cd {0}
    cmsenv
    cd -
    exec "$@"
    """.format(os.environ["LOCALRT"])

    wrapfile = os.path.join(config['outdir'], 'w.sh')
    with open(wrapfile, 'w') as f:
        f.write(wrap)
    os.chmod(wrapfile, os.stat(wrapfile).st_mode | stat.S_IEXEC)

    configfile = os.path.join(config['outdir'], 'run.yaml')
    with open(configfile, 'w') as f:
        yaml.dump(config, f)

    data = os.path.join(os.environ['LOCALRT'], 'src', 'EffectiveTTV', 'EffectiveTTV', 'data')
    shutil.copy(os.path.join(data, 'matplotlibrc'), config['outdir'])

    def cardify(name):
        return os.path.join(config['outdir'], '{}.txt'.format(name))


    print 'combineCards.py {} > {}'.format(os.path.join(config['cards']['2l'], 'A*.txt'), cardify('2l'))
    subprocess.call('combineCards.py {} > {}'.format(os.path.join(config['cards']['2l'], 'A*.txt'), cardify('2l')), shell=True)
    subprocess.call('combineCards.py {} > {}'.format(os.path.join(config['cards']['3l'], 'B*.txt'), cardify('3l')), shell=True)
    subprocess.call('combineCards.py {} > {}'.format(os.path.join(config['cards']['4l'], 'B*.txt'), cardify('4l')), shell=True)


    with open(cardify('4l'), 'r') as f:
        card = f.read()
    with open(cardify('4l'), 'w') as f:
        f.write(card[:card.find('nuisance parameters') + 19])
        f.write('''
----------------------------------------------------------------------------------------------------------------------------------
shapes *      ch1  FAKE
shapes *      ch2  FAKE''')
        f.write(card[card.find('nuisance parameters') + 19:])


    subprocess.call('combineCards.py {} {} > {}'.format(cardify('3l'), cardify('4l'), cardify('ttZ')), shell=True)
    subprocess.call('cp {} {}'.format(cardify('2l'), cardify('ttW')), shell=True)
    subprocess.call('combineCards.py {} {} > {}'.format(cardify('ttZ'), cardify('ttW'), cardify('2d')), shell=True)
    subprocess.call('combineCards.py {} {} > {}'.format(cardify('ttZ'), cardify('ttW'), cardify('ttV_np')), shell=True)

    with open(cardify('ttV_np'), 'r') as f:
        card = f.read()

    processes = re.compile(r'\nprocess.*')

    for index, process in enumerate(['ttW', 'ttZ']):
        names, numbers = processes.findall(card)
        for column in [i for i, name in enumerate(names.split()) if name == process]:
            number = numbers.split()[column]
            card = card.replace(numbers, numbers.replace(number, '{}'.format(index * -1)))

    jmax = re.search('jmax (\d*)', card).group(0)
    card = card.replace(jmax, 'jmax {}'.format(len(set(names.split()[1:])) - 1))

    with open(cardify('2d'), 'w') as f:
        f.write(card)

    systematics = {}
    systematics['Q2_ttZ'] = '\nQ2_ttZ                  lnN     '
    systematics['Q2_ttW'] = '\nQ2_ttW                  lnN     '
    systematics['Q2_ttH'] = '\nQ2_ttH                  lnN     '
    systematics['PDF_gg'] = '\nPDF_gg                  lnN     '
    systematics['PDF_qq'] = '\nPDF_qq                  lnN     '

    def compose(kappas):
        if kappas['-'] == kappas['+']:
            return str(kappas['+'])
        else:
            return '{}/{}'.format(kappas['-'], kappas['+'])

    for name in names.split()[1:]:
        systematics['Q2_ttZ'] += '{:15s}'.format(compose(kappa['Q2_ttZ']) if name == 'ttZ' else '-')
        systematics['Q2_ttW'] += '{:15s}'.format(compose(kappa['Q2_ttW']) if name == 'ttW' else '-')
        systematics['Q2_ttH'] += '{:15s}'.format(compose(kappa['Q2_ttH']) if name == 'ttH' else '-')
        systematics['PDF_qq'] += '{:15s}'.format(compose(kappa['PDF_qq']) if name == 'ttW' else '-')
        if name == 'ttZ':
            systematics['PDF_gg'] += '{:15s}'.format(compose(kappa['PDF_gg']['ttZ']))
        elif name == 'ttH':
            systematics['PDF_gg'] += '{:15s}'.format(compose(kappa['PDF_gg']['ttH']))
        else:
            systematics['PDF_gg'] += '{:15s}'.format('-')

    kmax = re.search('kmax (\d*)', card).group(0)
    card = card.replace(kmax, 'kmax {}'.format(int(re.search('kmax (\d*)', card).group(1)) + 4))

    for line in card.split('\n'):
        if line.startswith('ttX'):
            card = re.sub(line, '#' + line, card)

    with open(cardify('ttV_np'), 'w') as f:
        f.write(card[:card.find('\ntheo group')])
        for line in systematics.values():
            f.write(line)

    makefile = os.path.join(config['outdir'], 'Makeflow')
    logging.info('writing Makeflow file to {}'.format(config['outdir']))
    with open(makefile, 'w') as f:
        factory = os.path.join(data, 'factory.json')
        msg = (
            '# to run, issue the following commands:\n'
            '# cd {}\n'
            '# nohup work_queue_factory -T condor -M ttV_FTW -C {} >& makeflow_factory.log &\n'
            '# then keep running this command until makeflow no longer submits jobs (may take a few tries)\n'
            '# makeflow -T wq -M ttV_FTW --wrapper ./w.sh --wrapper-input w.sh --archive\n'
        ).format(config['outdir'], factory)

        f.write(msg)
        logging.info(msg.replace('# ', ''))

    def makeflowify(inputs, outputs, cmd='run', rename=False):
        if isinstance(inputs, basestring):
            inputs = [inputs]
        if isinstance(outputs, basestring):
            outputs = [outputs]
        if isinstance(cmd, basestring):
            cmd = shlex.split(cmd)

        outs = ' '.join(outputs)
        ins = ' '.join(inputs)
        if rename:
            outs = ' '.join(["{0}->{1}".format(p, os.path.basename(p)) for p in outputs])

        with open(makefile, 'a') as f:
            s = frag.format(
                out=outs,
                ins=ins,
                cmd=' '.join(cmd))
            f.write(s)

    if 'indir' in config:
        files = glob.glob(os.path.join(config['indir'], '*.root'))
        for f in files:
            outputs = os.path.join('cross_sections', os.path.basename(f).replace('.root', '.npy'))
            makeflowify(['run.yaml'], outputs, ['run', '--parse', f, 'run.yaml'])

        inputs = [os.path.join('cross_sections', os.path.basename(f).replace('.root', '.npy')) for f in files] + ['run.yaml']
        inputs += glob.glob(os.path.join(config['indir'], '*.npy'))
        outputs = 'cross_sections.npy'
        makeflowify(inputs, outputs, ['run', '--concatenate', 'run.yaml'])
    elif 'cross sections' in config:
        shutil.copy(config['cross sections'], os.path.join(config['outdir'], 'cross_sections.npy'))
    else:
        raise RuntimeError('must specify either `indir` or `cross sections`')

    # makeflowify('ttZ.txt', 'ttZ.root', 'combine -M MaxLikelihoodFit ttZ.txt; mv higgsCombineTest.MaxLikelihoodFit.mH120.root ttZ.root')
    # makeflowify('ttW.txt', 'ttW.root', 'combine -M MaxLikelihoodFit ttW.txt; mv higgsCombineTest.MaxLikelihoodFit.mH120.root ttW.root')

    for analysis in ['2l', '3l', '4l', 'ttZ']:
        workspace = os.path.join(config['outdir'], 'workspaces', '{}.root'.format(analysis))
        card = cardify(analysis)
        makeflowify(card, workspace, ['text2workspace.py', card, '-o', workspace])
        best_fit = os.path.join(config['outdir'], 'best-fit-{}.root'.format(analysis))
        fit_result = os.path.join(config['outdir'], 'fit-result-{}.root'.format(analysis))
        cmd = 'combine -M MaxLikelihoodFit {} >& {}.fit.log; mv higgsCombineTest.MaxLikelihoodFit.mH120.root {}'.format(cardify(analysis), cardify(analysis), best_fit)
        cmd += ';mv mlfit.root {}'.format(fit_result)
        makeflowify(workspace, [best_fit, fit_result], cmd)


    workspace = os.path.join(config['outdir'], 'workspaces', '2d.root')
    cmd = [
        'text2workspace.py', cardify('2d'),
        '-P', 'HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel',
        '--PO', 'map=.*/ttZ:r_ttZ[1,0,4]',
        '--PO', 'map=.*/ttW:r_ttW[1,0,4]',
        '-o', workspace
    ]

    makeflowify([cardify('2d')], workspace, cmd)

    best_fit = os.path.join(config['outdir'], 'best-fit-2d.root')
    fit_result = os.path.join(config['outdir'], 'fit-result-2d.root')
    cmd = 'combine -M MultiDimFit {} --algo=singles >& {}.fit.log'.format(workspace, cardify('2d'))
    cmd += ';mv higgsCombineTest.MultiDimFit.mH120.root {}'.format(best_fit)
    cmd += ';mv multidimfit.root {}'.format(fit_result)
    makeflowify(workspace, [best_fit, fit_result], cmd)

    lowers = np.arange(1, config['2d points'], config['chunk size'])
    uppers = np.arange(config['chunk size'], config['2d points'] + config['chunk size'], config['chunk size'])

    # FIXME uncomment for 2d sm contours
    # scans = []
    # for index, (first, last) in enumerate(zip(lowers, uppers)):
    #     filename = 'higgsCombine_ttW_ttZ_2D_part_{}.MultiDimFit.mH120.root'.format(index)
    #     scan = os.path.join(config['outdir'], 'scans', filename)
    #     scans.append(scan)

    #     cmd = [
    #         'combine',
    #         '-M', 'MultiDimFit',
    #         workspace,
    #         '--algo=grid',
    #         '--points={}'.format(config['2d points']),
    #         '-n', '_ttW_ttZ_2D_part_{}'.format(index),
    #         '--firstPoint {}'.format(first),
    #         '--lastPoint {}'.format(last),
    #         '; mv {} {}'.format(filename, scan)
    #     ]

    #     makeflowify(workspace, scan, cmd)

    # outfile = os.path.join(config['outdir'], 'scans', '2d.total.root')
    # makeflowify(scans, outfile, ['hadd', '-f', outfile] + scans)

    lowers = np.arange(1, config['1d points'], config['chunk size'])
    uppers = np.arange(config['chunk size'], config['1d points'] + config['chunk size'], config['chunk size'])

    combinations = [sorted(list(x)) for x in itertools.combinations(config['operators'], config['dimension'])]
    for operators in combinations:
        label = '_'.join(operators)
        workspace = os.path.join(config['outdir'], 'workspaces', '{}.root'.format(label))
        cmd = [
            'text2workspace.py', os.path.join(config['outdir'], 'ttV_np.txt'),
            '-P', 'EffectiveTTV.EffectiveTTV.models:eff_op',
            '--PO', 'config={}'.format(os.path.join(config['outdir'], 'run.yaml')),
            ' '.join(['--PO process={}'.format(x) for x in config['processes']]),
            ' '.join(['--PO poi={}'.format(x) for x in operators]),
            '-o', workspace
        ]

        makeflowify('cross_sections.npy', workspace, cmd)

        best_fit = os.path.join(config['outdir'], 'best-fit-{}.root'.format(label))
        fit_result = os.path.join(config['outdir'], 'fit-result-{}.root'.format(label))
        cmd = 'combine -M MultiDimFit {} --algo=singles '.format(workspace)
        cmd += ' --setPhysicsModelParameters {}'.format(','.join(['{}=0.0'.format(x) for x in operators]))
        # convergence of the loop expansion requires c < (4 * pi)^2
        # see section 7 in https://arxiv.org/pdf/1205.4231.pdf
        # cmd += ' --setPhysicsModelParameterRanges {}'.format(':'.join(['{}=-158,158'.format(x) for x in operators]))
        # FIXME change this back for Geoff's question
        # FIXME consider using autoBoundsPOIs and autoMaxPOIs, not sure if they work
        cmd += ' --setPhysicsModelParameterRanges {}'.format(':'.join(['{}=-5,5'.format(x) for x in operators]))
        # cmd += ' --setPhysicsModelParameterRanges {}'.format(':'.join(['{}=-3,3'.format(x) for x in operators]))
        cmd += ' -t -1 ' if config['asimov data'] else ''
        cmd += ';mv higgsCombineTest.MultiDimFit.mH120.root {}'.format(best_fit)
        cmd += ';mv multidimfit.root {}'.format(fit_result)
        # FIXME do scans first, then set parameter ranges from NLL fit
        makeflowify(workspace, [best_fit, fit_result], cmd)
        cmd = ['run', '--fluctuate', label, '150000', 'run.yaml']
        makeflowify(['run.yaml', fit_result], os.path.join(config['outdir'], 'fluctuations-{}.npy'.format(label)), cmd)

        scans = []
        for index, (first, last) in enumerate(zip(lowers, uppers)):
            filename = 'higgsCombine_{}_part_{}.MultiDimFit.mH120.root'.format(label, index)
            scan = os.path.join(config['outdir'], 'scans', filename)
            scans.append(scan)

            cmd = [
                'combine',
                '-M', 'MultiDimFit',
                workspace,
                '--algo=grid',
                '--points={}'.format(config['1d points']),
                '--setPhysicsModelParameters', ','.join(['{}=0.0'.format(x) for x in operators]),
                # '--setPhysicsModelParameterRanges', ':'.join(['{}=-158,158'.format(x) for x in operators]),
                # '--setPhysicsModelParameterRanges', ':'.join(['{}=-5,5'.format(x) for x in operators]),
                '--setPhysicsModelParameterRanges', ':'.join(['{}=-3,3'.format(x) for x in operators]),
                # FIXME change back
                '--autoRange={}'.format('15' if config['asimov data'] else '20'),
                ' -t -1 ' if config['asimov data'] else '',
                '-n', '_{}_part_{}'.format(label, index),
                '--firstPoint {}'.format(first),
                '--lastPoint {}'.format(last),
                '; mv {} {}'.format(filename, scan)
            ]

            makeflowify(workspace, scan, cmd)

        outfile = os.path.join(config['outdir'], 'scans', '{}.total.root'.format(label))
        makeflowify(scans, outfile, ['hadd', '-f', outfile] + scans)

        # makeflowify(outfile, [], ['rm'] + scans)

    inputs = [os.path.join(config['outdir'], 'scans', '{}.total.root'.format('_'.join(o))) for o in combinations]
    inputs += ['cross_sections.npy', 'run.yaml']
    plot_rt = os.path.join(os.path.dirname(os.environ['LOCALRT']), 'CMSSW_8_1_0_pre16')
    # makeflowify(inputs, [], ['LOCAL', 'sh', os.path.join(data, 'env.sh'), 'run', '--plot', 'run.yaml'])
    for operator in config['operators']:
        fluctuations = os.path.join(config['outdir'], 'fluctuations-{}.npy'.format(operator))
        cmd = ['cd', plot_rt, '; eval `scramv1 runtime -sh`; cd -', 'run', '--plot', operator, 'run.yaml']
        makeflowify(inputs + [fluctuations], [], cmd)


def parse(args, config):
    import DataFormats.FWLite

    def get_collection(run, ctype, label):
        handle = DataFormats.FWLite.Handle(ctype)
        try:
            run.getByLabel(label, handle)
        except:
            raise

        return handle.product()

    logging.info('parsing {}'.format(args.parse))

    for run in DataFormats.FWLite.Runs(args.parse):
        cross_section = get_collection(run, 'LHERunInfoProduct', 'externalLHEProducer::LHE').heprup().XSECUP[0]
        operators = np.array(get_collection(run, 'vector<string>', 'annotator:operators:LHE'))
        process = str(get_collection(run, 'std::string', 'annotator:process:LHE'))
        dtype = [(name, 'f8') for name in operators]
        coefficients = np.array(tuple(get_collection(run, 'vector<double>', 'annotator:wilsonCoefficients:LHE')), dtype=dtype)

        row = np.array((coefficients, cross_section), dtype=[('coefficients', coefficients.dtype, coefficients.shape), ('cross section', 'f8')])

        try:
            cross_sections = np.vstack([cross_sections, row])
        except UnboundLocalError:
            cross_sections = row

    outfile = os.path.join(config['outdir'], 'cross_sections', os.path.basename(args.parse).replace('.root', '.npy'))
    np.save(outfile, {process: cross_sections})


def concatenate(args, config):
    files = glob.glob(os.path.join(config['outdir'], 'cross_sections', '*.npy'))
    if 'indir' in config:
        files += glob.glob(os.path.join(config['indir'], '*.npy'))
    res = {}
    for f in files:
        info = np.load(f)[()]
        for process, cross_sections in info.items():
            try:
                res[process] = np.vstack([res[process], cross_sections])
            except KeyError:
                res[process] = cross_sections

    outfile = os.path.join(config['outdir'], 'cross_sections.npy')
    np.save(outfile, res)

    dump_mus(config)
