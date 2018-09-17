import argh
import pathlib
import evaluate

'''
CORE LAUNCH METHODS: launch and qsub_launch
'''
log = []

def launch(params):
    s = 'python3.6 /proj/smallfry/git/smallfry/experiments/evaluation/evaluate.py eval-embeddings %s  %s %s %s' % params
    return s

def qsub_launch(method, params):
    return 'qsub -V -b y -wd /proj/smallfry/qsub_logs'+launch(method, params)

'''
GLOBAL PATHS CODED HERE
'''
base_embed_path_head = '/proj/smallfry/base_embeddings'
launch_path = '/proj/smallfry/launches/maker'
base_outputdir = '/proj/smallfry/embeddings'

'''
HELPER METHODS FOR COMMON SWEEP STYLES (and logging)
'''
def log_launch(name):
    log_launch_path = str(pathlib.PurePath( launch_path, name ))
    with open(log_launch_path, 'w+') as llp:
        llp.write('\n'.join(log))

def forall_in_rungroup(evaltype, rungroup, seeds, params=None, qsub=True):
    '''a subroutine for complete 'sweeps' of params'''
    l = qsub_launch if qsub else launch
    for seed in seeds:
        rungroup_qry = str(pathlib.PurePath(base_outputdir,rungroup+'/*') 
        for e in glob.glob(rungroup_qry):
            #speical params not support yet TODO
            cmd = l(evaltype,(
                        e,
                        evaltype,
                        '/',
                        seed)
            log.append(cmd)

def get_log_name(name, rungroup):
    return maker.get_date_str() + ':' + rungroup + ':' + name

'''
LAUNCH ROUTINES BELOW THIS LINE =========================
'''

def launch1_demo(name):
    #date of code Sept 16, 2018
    rungroup = 'first-official-testrun'
    evaltypes = ['intrinsics','synthetics','QA']
    params = dict()
    for evaltype in evaltypes:
        seeds = [6297]
        forall_in_rungroup(evaltype, rungroup, seeds, qsub=False)
    log_launch(get_log_name(name, rungroup))


#IMPORTANT!! this line determines which cmd will be run
cmd = [launch1_demo]

parser = argh.ArghParser()
parser.add_commands(cmd)

if __name__ == '__main__':
    parser.dispatch()
