import os
import sys
import socket
import json
import datetime
import logging
import pathlib
import time
import random
import subprocess
import argparse
import numpy as np
import getpass
try:
    import tensorflow as tf
except ImportError:
    pass
try:
    import torch
except ImportError:
    pass

config = {}

def init(runtype):
    if runtype == 'train':
        parser = init_train_parser()
    elif runtype == 'compress':
        parser = init_compress_parser()
    elif runtype == 'evaluate':
        parser = init_evaluate_parser()
    init_config(parser, runtype)
    init_random_seeds()

def init_train_parser():
    """Initialize cmd-line parser for embedding training."""
    parser = argparse.ArgumentParser()
    add_shared_args(parser)
    parser.add_argument('--embedtype', type=str, required=True,
        choices=['glove'],
        help='Name of embeddings training algorithm.')
    parser.add_argument('--corpus', type=str, required=True,
        choices=['text8','wiki','wiki400k'],
        help='Natural language dataset used to train embeddings')
    parser.add_argument('--rungroup', type=str, required=True,
        help='Rungroup for organization')
    parser.add_argument('--embeddim', type=int, required=True,
        help='Dimension for generated embeddings')
    parser.add_argument('--threads', type=int, default=8,
        help='Number of threads to spin up')
    parser.add_argument('--epochs', type=int, default=50,
        help='Number of iterations to optimize over')
    parser.add_argument('--lr', type=float, default=0.05,
        help='Learning rate for embedding training.')
    return parser

def init_compress_parser():
    """Initialize cmd-line parser for embedding compression."""
    parser = argparse.ArgumentParser()
    add_shared_args(parser)
    parser.add_argument('--embedtype', type=str, required=True,
        choices=['glove400k','glove10k','glove-wiki-am','glove-wiki400k-am','fasttext1m'],
        help='Name of embedding to compress')
    parser.add_argument('--embeddim', type=int, required=True,
        help='Dimension of embeddings to use.')
    parser.add_argument('--compresstype', type=str, required=True,
        choices=['uniform','kmeans','dca','pca','nocompress'],
        help='Name of compression method to use (uniform, kmeans, dca, nocompress).')
    parser.add_argument('--rungroup', type=str, required=True,
        help='Name of rungroup')
    # required for all compression types except for PCA.
    parser.add_argument('--bitrate', type=int, required=False, default=-1,
        help='Bitrate.  Note not exact for some methods, but as close as possible.')
    parser.add_argument('--seed', type=int, required=True,
        help='Random seed to use for experiment.')
    ### Begin uniform quantization hyperparameters
    parser.add_argument('--stoch', action='store_true', 
        help='Specifies whether stochastic quantization should be used.')
    parser.add_argument('--adaptive', action='store_true', 
        help='Specifies whether range for uniform quantization should be optimized.')
    parser.add_argument('--skipquant', action='store_true', 
        help='Specifies whether clipping should be performed without quantization (for ablation).')
    ### End uniform quantization hyperparameters
    ### Begin DCA hyperparameters
    # The number of DCA codebooks 'm' is determined from k and bitrate
    # k is a required argument for DCA training.
    parser.add_argument('--k', type=int, default=-1,
        help='Codebook size for DCA, must be a power of 2.')
    parser.add_argument('--lr', type=float, default=0.0001,
        help='Learning rate for DCA training.')
    parser.add_argument('--batchsize', type=int, default=64,
        help='Batch size for DCA training.')
    parser.add_argument('--tau', type=float, default=1.0,
        help='Temperature parameter for DCA training.')
    parser.add_argument('--gradclip', type=float, default=0.001,
        help='Clipping of gradient norm for DCA training.')
    ### End DCA hyperparameters
    ### PCA hyperparameters
    parser.add_argument('--pcadim', type=int, required=False, default=-1,
        help='Dimension of embeddings to use for compressed PCA embeddings.')
    ### run for saving code books
    parser.add_argument('--codebook-saving', action='store_true',
        help='save codebooks codes and embedding; this avoid overwrite the old embeddings')
    return parser

def init_evaluate_parser():
    """Initialize cmd-line parser for embedding evaluation."""
    parser = argparse.ArgumentParser()
    add_shared_args(parser)
    parser.add_argument('--evaltype', type=str, required=True,
        choices=['qa','intrinsics','synthetics','synthetics-large-dim','sentiment','translation'],
        help='Evaluation type.')
    parser.add_argument('--embedpath', type=str, required=True,
        help='Path to embedding to evaluate.')
    parser.add_argument('--dataset', type=str,
        choices=['mr','subj','cr','sst','trec','mpqa'],
        help='Sentiment dataset to evaluate.')
    parser.add_argument('--tunelr', action='store_true',
        help='Boolean specifying whether or not the learning rate should be tuned.')
    parser.add_argument('--lr', type=float, default='-1',
        help='Learning rate to use for sentiment analysis.')
    parser.add_argument('--epochs', type=int, default=100,
        help='Number of epochs to use for sentiment analysis training.')
    #parser.add_argument('--datapath', type=str, default="",
    #    help="the data file path")
    return parser

def add_shared_args(parser):
    parser.add_argument('--cuda', action='store_true',
        help='Specifies whether GPU should be used.')
    parser.add_argument('--debug', action='store_true',
        help='If true, can have local git changes when running this.')

def init_config(parser, runtype):
    global config
    config = vars(parser.parse_args())
    validate_config(runtype)
    orig_config = config.copy()
    if runtype == 'evaluate':
        config_path = config['embedpath'].replace('_compressed_embeds.txt','_final.json')
        config['compress-config'] = load_from_json(config_path)
        config['rungroup'] = 'eval-' + config['compress-config']['rungroup']
        config['seed'] = config['compress-config']['seed']
    elif runtype == 'train':
        config['embedname'] = get_train_embedding_name()
        config['seed'] = 1 # TODO: do we need to change this?
        config['vocab-file'], config['cooc-file'], config['raw-file'] = get_corpus_info(config['corpus'])
        config['vocab'] = sum(1 for line in open(config['vocab-file'], 'r', encoding='utf8'))
    config['runname'] = get_runname(parser, runtype)
    config['datestr'] = get_date_str()
    config['rungroup'] =  '{}-{}'.format(config['datestr'], config['rungroup'])
    config['full-runname'] = get_full_runname(runtype)
    config['basedir'] = get_base_dir()
    config['rundir'] = get_and_make_run_dir(runtype)
    config['runtype'] = runtype
    init_logging()
    config['githash'], config['gitdiff'] = get_git_hash_and_diff() # might fail
    logging.info('Command line arguments: {}'.format(' '.join(sys.argv[1:])))
    save_to_json(orig_config, get_filename('_orig_config.json'))
    save_current_config()

def save_current_config():
    save_to_json(config, get_filename('_config.json'))

def validate_config(runtype):
    if runtype == 'train':
        pass # nothing to validate here
    elif runtype == 'compress':
        if config['compresstype'] != 'pca':
            assert config['bitrate'] >= 1 and config['bitrate'] <= 32, \
                'Must specify bitrate between 1 and 32.'
        if config['compresstype'] == 'dca':
            assert config['k'] != -1, 'Must specify k for DCA training.'
            assert np.log2(config['k']) == np.ceil(np.log2(config['k'])), \
                'k must be a power of 2.'
        elif config['compresstype'] == 'nocompress':
            assert config['bitrate'] == 32
        elif config['compresstype'] == 'pca':
            assert config['pcadim'] > 0 and config['pcadim'] <= config['embeddim'], \
                'pcadim must be a positive integer at most the size of the original embeddings.'
        if config['embedtype'] == 'glove400k' or config['embedtype'] == 'glove10k':
            assert config['embeddim'] in (50,100,200,300)
        elif config['embedtype'] == 'glove-wiki-am' or config['embedtype'] == 'glove-wiki400k-am':
            assert config['embeddim'] in (25,50,100,200,400,800)
        elif config['embedtype'] == 'fasttext1m':
            assert config['embeddim'] == 300
    elif runtype == 'evaluate':
        assert '_compressed_embeds.txt' in config['embedpath']
        if config['evaltype'] == 'sentiment':
            assert config['dataset'], 'Must specify dataset for sentiment eval.'
    if runtype != 'evaluate':
        assert '_' not in config['rungroup'], 'rungroups should not have underscores'

def get_runname(parser, runtype):
    runname = ''
    if runtype == 'train':
        to_skip = ('rungroup')
    elif runtype == 'compress':
        to_skip = ('embedtype','rungroup')
    elif runtype == 'evaluate':
        to_skip = ('embedpath')

    for key,val in non_default_args(parser, config):
        if key not in to_skip:
            runname += '{},{}_'.format(key,val)
    # remove the final '_' from runname
    return runname[0:-1] if runname[-1] == '_' else runname

def get_full_runname(runtype):
    if runtype == 'train':
        return 'rungroup,{}_{}'.format(
            config['rungroup'], config['runname'])
    elif runtype == 'compress':
        return 'embedtype,{}_rungroup,{}_{}'.format(
            config['embedtype'], config['rungroup'], config['runname'])
    elif runtype == 'evaluate':
        return 'rungroup,{}_{}'.format(
            config['rungroup'], config['runname'])

def get_and_make_run_dir(runtype):
    rundir = ''
    if runtype == 'train':
        rundir = str(pathlib.PurePath(
            config['basedir'], 'base_embeddings',
            config['embedname'], config['rungroup'], config['runname']))
    elif runtype == 'compress':
        rundir = str(pathlib.PurePath(
            config['basedir'], 'embeddings',
            config['embedtype'], config['rungroup'], config['runname']))
    elif runtype == 'evaluate':
        rundir = config['compress-config']['rundir']
    ensure_dir(rundir)
    return rundir

def get_train_embedding_name():
    # 'am' is an indication that it was trained by Avner May, and is thus not
    # a pre-trained embedding.
    return '{}-{}-am'.format(config['embedtype'], config['corpus'])

def init_random_seeds():
    """Initialize random seeds."""
    if 'torch' in sys.modules:
        torch.manual_seed(config['seed'])
        if config['cuda']:
            torch.cuda.manual_seed(config['seed'])
    if 'tensorflow' in sys.modules:
        tf.set_random_seed(config['seed'])
    np.random.seed(config['seed'])
    random.seed(config['seed'])

def args_set_at_cmdline():
    args_set = [s[2:] for s in sys.argv[1:] if (len(s) > 2 and s[0:2] == '--')]
    assert len(args_set) > 0, 'There must be a cmdline arg.'
    return args_set

def non_default_args(parser, args):
    non_default = []
    for action in parser._actions:
        default = action.default
        key = action.dest
        if key in args:
            val = args[key]
            if val != default:
                non_default.append((key,val))
    assert len(non_default) > 0, 'There must be a non-default arg.'
    return non_default

def get_git_hash_and_diff():
    git_hash = None
    git_diff = None
    if not is_windows():
        try:
            wd = os.getcwd()
            git_repo_dir = str(pathlib.PurePath(get_base_dir(), 'git','smallfry'))
            os.chdir(git_repo_dir)
            git_hash = str(subprocess.check_output(
                ['git','rev-parse','--short','HEAD']).strip())[2:9]
            git_diff = str(subprocess.check_output(['git','diff']).strip())[3:]
            if not config['debug']:
                # if not in debug mode, local repo changes are not allowed.
                assert git_diff == '', 'Cannot have any local changes'
            os.chdir(wd)
            logging.info('Git hash {}'.format(git_hash))
            logging.info('Git diff {}'.format(git_diff))
        except FileNotFoundError:
            logging.info('Unable to get git hash.')
    return git_hash, git_diff

def get_date_str():
    return '{:%Y-%m-%d}'.format(datetime.date.today())

def ensure_dir(dir):
    pathlib.Path(dir).mkdir(parents=True, exist_ok=True)

def get_filename(suffix):
    """Return filename which is 'rundir/full-runname + suffix'."""
    return str(pathlib.PurePath(
        config['rundir'], config['full-runname'] + suffix))

def is_windows():
    """Determine if running on windows OS."""
    return os.name == 'nt'

def get_base_dir():
    hostname = socket.gethostname()
    if is_windows():
        username = ('Avner' if (hostname == 'Avner-X1Carbon')
                    else 'avnermay')
        path = 'C:\\Users\\{}\\Babel_Files\\smallfry'.format(username)
    # elif hostname == 'DN0a22a222.SUNet':
    # elif 'DN' in hostname and '.SUNet' in hostname:
    elif getpass.getuser() == 'Jian':
        path = '/Users/Jian/Data/research/smallfry/'
    elif '.stanford.edu' in hostname and getpass.getuser() == 'zjian':
        path = '/dfs/scratch0/zjian/smallfry'
    elif '.stanford.edu' in hostname:
        path = '/dfs/scratch0/avnermay/smallfry'
    else:
        path = '/proj/smallfry'
    return path

def get_home_dir():
    hostname = socket.gethostname()
    if is_windows() or '.stanford.edu' in hostname:
        return get_base_dir()
    # elif hostname == 'DN0a22a222.SUNet':
    # elif 'DN' in hostname and '.SUNet' in hostname:
    elif getpass.getuser() == 'Jian':
        return get_base_dir()
    elif '.stanford.edu' in hostname and getpass.getuser() == 'zjian':
        return get_base_dir()
    else:
        return '/home/ubuntu'

def get_git_dir():
    hostname = socket.gethostname()
    if is_windows():
        username = ('Avner' if (hostname == 'Avner-X1Carbon')
                    else 'avnermay')
        path = 'C:\\Users\\{}\\Git\\smallfry'.format(username)
    # elif hostname == 'DN0a22a222.SUNet':
    # elif 'DN' in hostname and '.SUNet' in hostname:
    elif getpass.getuser() == 'Jian':
        path = '/Users/Jian/Data/research/smallfry/'
    elif '.stanford.edu' in hostname and getpass.getuser() == 'zjian':
        path = '/dfs/scratch0/zjian/smallfry'
    else:
        path = '/proj/smallfry/git/smallfry'
    return path

def get_src_dir():
    return os.path.dirname(os.path.abspath(__file__))

def get_corpus_info(corpus):
    dr = str(pathlib.PurePath(get_base_dir(), 'corpora', corpus))
    if corpus == 'wiki':
        vocab = str(pathlib.PurePath(dr, 'vocab_minCount_5_ws_15.txt'))
        cooc = str(pathlib.PurePath(dr, 'cooccurrence_minCount_5_ws_15.shuf.bin'))
        raw = str(pathlib.PurePath(dr, 'wiki.en.txt'))
    if corpus == 'wiki400k':
        vocab = str(pathlib.PurePath(dr, 'vocab_wiki400k.txt'))
        cooc = str(pathlib.PurePath(dr, 'cooccurrence_wiki400k.shuf.bin'))
        # raw file is same as for 'wiki' above.
        raw = str(pathlib.PurePath(dr, 'N/A'))
    elif corpus == 'text8':
        vocab = str(pathlib.PurePath(dr, 'text8_vocab.txt'))
        cooc = str(pathlib.PurePath(dr, 'text8_cooccurrence.shuf.bin'))
        raw = str(pathlib.PurePath(dr, 'N/A'))
    return vocab, cooc, raw

def get_embedding_vocab(embedtype):
    if embedtype == 'glove400k':
        vocab = 400000
    elif embedtype == 'glove10k':
        vocab = 10000
    elif embedtype == 'glove-wiki-am':
        vocab = 3801686
    elif embedtype == 'glove-wiki400k-am':
        vocab = 400001
    elif embedtype == 'fasttext1m':
        vocab = 999994
    return vocab

def get_large_embedding_dim(embedtype):
    return 400 if embedtype == 'glove-wiki400k-am' else 300

def get_base_embed_info(embedtype, embeddim):
    '''Get path to embedding, and size of vocab for embedding'''
    path = ''
    basedir = str(pathlib.PurePath(
        get_base_dir(), 'base_embeddings', embedtype
    ))
    vocab = get_embedding_vocab(embedtype)
    if embedtype == 'glove400k':
        file_format_str = 'glove.6B.{}d.txt'
    elif embedtype == 'glove10k':
        file_format_str = 'glove.6B.{}d.10k.txt'
    elif embedtype == 'glove-wiki-am':
        file_format_str = str(pathlib.PurePath(
            '2018-12-14-trainGlove',
            'embedtype,glove_corpus,wiki_embeddim,{}_threads,72',
            'rungroup,2018-12-14-trainGlove_embedtype,glove_corpus,wiki_embeddim,{}_threads,72_embeds.txt'
        ))
    elif embedtype == 'glove-wiki400k-am':
        if embeddim == 800:
            file_format_str = str(pathlib.PurePath(
                '2018-12-18-trainGlove',
                'embedtype,glove_corpus,wiki400k_embeddim,{}_threads,72_lr,0.025',
                'rungroup,2018-12-18-trainGlove_embedtype,glove_corpus,wiki400k_embeddim,{}_threads,72_lr,0.025_embeds.txt'
            ))
        else:
            file_format_str = str(pathlib.PurePath(
                '2018-12-18-trainGlove',
                'embedtype,glove_corpus,wiki400k_embeddim,{}_threads,72',
                'rungroup,2018-12-18-trainGlove_embedtype,glove_corpus,wiki400k_embeddim,{}_threads,72_embeds.txt'
            ))
    elif embedtype == 'fasttext1m':
        file_format_str = 'wiki-news-{}d-1M.vec'
    path_format_str = str(pathlib.PurePath(basedir, file_format_str))
    # pass embeddim twice because of glove-wiki-am (it doesn't affect the others)
    path = path_format_str.format(embeddim, embeddim)
    return path,vocab

def init_logging():
    """Initialize logfile to be used for experiment."""
    log_filename = get_filename('.log')
    logging.basicConfig(filename=log_filename,
                        format='%(asctime)s %(message)s',
                        datefmt='[%m/%d/%Y %H:%M:%S]: ',
                        filemode='w', # this will overwrite existing log file.
                        level=logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    logging.getLogger('').addHandler(console)
    logging.info('Begin logging.')

def save_to_json(dict_to_write, path):
    with open(path, 'w') as f: json.dump(dict_to_write, f, indent=2)

def load_from_json(path):
    with open(path) as f: return json.load(f)

def load_embeddings(path):
    """
    Loads a GloVe or FastText format embedding at specified path. Returns a
    vector of strings that represents the vocabulary and a 2-D numpy matrix that
    is the embeddings.
    """
    logging.info('Beginning to load embeddings')
    with open(path, 'r', encoding='utf8') as f:
        lines = f.readlines()
        wordlist = []
        embeddings = []
        if is_fasttext_format(lines): lines = lines[1:]
        for line in lines:
            row = line.strip('\n').split(' ')
            wordlist.append(row.pop(0))
            embeddings.append([float(i) for i in row])
        embeddings = np.array(embeddings)
    assert len(wordlist) == embeddings.shape[0], 'Embedding dim must match wordlist length.'
    logging.info('Finished loading embeddings')
    return embeddings, wordlist

def get_embedding_dimension(embed_path):
    with open(embed_path) as f_embed:
        for line in f_embed:
            if not is_fasttext_format([line]):
                pieces = line.rstrip().split(' ')
                embed_dim = len(pieces) - 1
                logging.info('Loading ' + str(embed_dim) +
                                ' dimensional embedding')
                break
    assert embed_dim > 0
    return embed_dim

def is_fasttext_format(lines):
    first_line = lines[0].strip('\n').split(' ')
    return len(first_line) == 2 and first_line[0].isdigit() and first_line[1].isdigit()

def save_embeddings(path, embeds, wordlist):
    ''' save embeddings in text file format'''
    logging.info('Beginning to save embeddings')
    with open(path, 'w', encoding='utf8') as f:
        for i in range(len(wordlist)):
            strrow = ' '.join([str(embed) for embed in embeds[i,:]])
            f.write('{} {}\n'.format(wordlist[i], strrow))
    logging.info('Finished saving embeddings')
    # ANOTHER VERSION, WHICH WRITES FILE ALL AT ONCE
    # all_strs = [0] * range(len(wordlist))
    # for i in range(len(wordlist)):
    #     strrow = ' '.join([str(embed) for embed in embeds[i,:]])
    #     all_strs[i] = '{} {}\n'.format(wordlist[i], strrow)
    # full_str = ''.join(all_strs)
    # with open(path, 'w', encoding='utf8') as file:
    #     file.write(full_str)

# def perform_command_local(command):
#     ''' performs a command -- original author: MAXLAM'''
#     out = str(subprocess.check_output(command,
#             stderr=subprocess.STDOUT).decode('utf-8'))
#     return out

def save_codebooks(path, codes, codebook):
    np.save(path.split(".txt")[0] + "_codes.npy", codes)
    np.save(path.split(".txt")[0] + "_codebook.npy", codebook)


def perform_command_local(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    all_output = []
    for line in iter(p.stdout.readline, b''):
        # remove b' from beginning, and ' from end.
        line = str(line.rstrip())[2:-1]
        logging.info(line)
        all_output.append(line)
    return all_output

def delta_approximation(K, K_tilde, lambda_=1e-3):
    """ Compute the smallest D1 and D2 such that
    (1 - D1)(K + lambda_ I) <= K_tilde + lambda_ I <= (1 + D2)(K + lambda_ I),
    where the inequalities are in semidefinite order.
    """
    logging.info('Beginning to compute delta_approximation')
    if type(K) == torch.Tensor and type(K_tilde) == torch.Tensor:
        # todo: what if K and K_tilde are on GPU?
        K = K.numpy()
        K_tilde = K_tilde.numpy()
    # make K_tilde symmetric
    #K = (K + K.T)/2
    #K_tilde = (K_tilde + K_tilde.T)/2
    n, m = K.shape
    n_tilde, m_tilde = K_tilde.shape
    assert n == m and n_tilde == m_tilde, "Kernel matrix must be square"
    assert n == n_tilde, "K and K_tilde must have the same shape"
    assert np.allclose(K, K.T) and np.allclose(K_tilde, K_tilde.T), "Kernel matrix must be symmetric"
    # Compute eigen-decomposition of K + lambda_ I, of the form V @ np.diag(sigma) @ V.T
    sigma, V = np.linalg.eigh(K)
    #assert np.all(sigma >= 0), "Kernel matrix K must be positive semidefinite"
    sigma += lambda_
    # Whitened K_tilde: np.diag(1 / np.sqrt(sigma)) @ V.T @ K_tilde @ V @ np.diag(1 / np.sqrt(sigma))
    K_tilde_whitened = V.T.dot(K_tilde.dot(V)) / np.sqrt(sigma) / np.sqrt(sigma)[:, np.newaxis]
    K_whitened = np.diag(1 - lambda_ / sigma)
    sigma_final, _ = np.linalg.eigh(K_tilde_whitened - K_whitened)
    lambda_min = sigma_final[0]
    lambda_max = sigma_final[-1]
    logging.info('Finished computing delta_approximation')
    assert lambda_max >= lambda_min
    # return delta1, delta2, max(delta2, delta1/(1-delta1))
    return -lambda_min, lambda_max, max(lambda_max, -lambda_min/(1.0 + lambda_min))

def eigen_overlap(X1, X2):
    # X1 and X2 are n x d where n is the dataset size, d is the feature dimensionality
    assert X1.shape[0] == X2.shape[0]
    U1, S1, _ = np.linalg.svd(X1, full_matrices=False)
    U2, S2, _ = np.linalg.svd(X2, full_matrices=False)
    normalizer = max(X1.shape[1], X2.shape[1])
    return np.linalg.norm(U1.T @ U2, ord='fro')**2 / normalizer
