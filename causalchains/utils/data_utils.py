################################
# Data Utils for generating
# plain old text (The Book Corpus)
# The input is assumed to be a pretokenized text file
# with a single sentence per line
#
# Uses texttorch stuff, so make sure thats installed 
################################
import torch 
import torch.nn as nn
import numpy as np
import math
import json
import pickle
from torch.utils.data import Dataset, DataLoader
import torchtext.data as ttdata
import torchtext.datasets as ttdatasets
from torchtext.vocab import Vocab
from collections import defaultdict, Counter

#Reserved Special Tokens
PAD_TOK = "<pad>"
UNK_TOK = "<unk>"

#PAD has an id of 1
#UNK has id of 0

def create_event_vocab(filename, max_size=None, min_freq=1, savefile=None, specials = [UNK_TOK, PAD_TOK]):
    """
    Create a vocabulary for the bank of events
    Args
        filename (str) : filename to induce vocab from
        max_size (int) : max size of the vocabular (None = Unbounded)
        min_freq (int) : the minimum times a word must appear to be 
        placed in the vocab
        savefile (str or None) : file to save vocab to (return it if None)
        specials (list) : list of special tokens 
    returns Vocab object
    """
    count = Counter()
    with open(filename, 'r') as fi:
        for line in fi:
            json_line = json.loads(line)
            count.update([json_line['e1']])

    voc = Vocab(count, max_size=max_size, min_freq=min_freq, specials=specials)
    if savefile is not None:
        with open(savefile, 'wb') as fi:
            pickle.dump(voc, fi)
        return None
    else:
        return voc


def create_text_vocab(filename, max_size=None, min_freq=1, savefile=None, specials = [UNK_TOK, PAD_TOK]):
    count = Counter()
    with open(filename, 'r') as fi:
        for line in fi:
            json_line = json.loads(line)
            e1_text = json_line['e1_text'].lower()
            for tok in e1_text.split(" "):
                count.update([tok.rstrip('\n')])

    voc = Vocab(count, max_size=max_size, min_freq=min_freq, specials=specials)
    if savefile is not None:
        with open(savefile, 'wb') as fi:
            pickle.dump(voc, fi)
        return None
    else:
        return voc

def load_vocab(filename):
    #load vocab from json file
    with open(filename, 'rb') as fi:
        voc = pickle.load(fi)
    return voc


class ExtendableField(ttdata.Field):
    'A field class that allows the vocab object to be passed in' 
    #This is to avoid having to calculate the vocab every time 
    #we want to run
    def __init__(self, vocab, *args, **kwargs):
        """
        Args    
            Same args as Field except
            vocab (torchtext Vocab) : vocab to init with
                set this to None to init later

            USEFUL ARGS:
            tokenize
            fix_length (int) : max size for any example, rest are padded to this (None is defualt, means no limit)
            include_lengths (bool) : Whether to return lengths with the batch output (for packing)
        """

        super(ExtendableField, self).__init__(*args, pad_token=PAD_TOK, batch_first=True, **kwargs)
        if vocab is not None:
            self.vocab = vocab
            self.vocab_created = True
        else:
            self.vocab_created = False

    def init_vocab(self, vocab):
        if not self.vocab_created:
            self.vocab = vocab
            self.vocab_created = True

    def build_vocab(self):
        raise NotImplementedError


class InstanceDataset(ttdata.Dataset):
    'Dataset for a single training instance (event 1, event 2, text, other events)'

    def __init__(self, path, event_vocab, text_vocab, min_size=5, filter_unk_events=True):

        """
        Args
            path (str) : Filename of text file with dataset
            vocab (Torchtext Vocab object)
            filter_unk_events (bool) : Remove instances where either e1 or e2 are unk
            min_size : the minimum size of text fields, pad to this size if it is not larger
        """
        def pad_to_size(arr, voc): #Add extra pads if the length is still less than min length
            #This is computed after padding and after numericalize
            for b in arr:
                if len(b) < min_size:
                    rem = min_size - len(b)
                    b.extend([voc.stoi[PAD_TOK]]*rem)
            return arr

        e1_text = ExtendableField(text_vocab, sequential=True, include_lengths=True, postprocessing=pad_to_size)
        e1 = ExtendableField(event_vocab, sequential=False)
        e2 = ExtendableField(event_vocab, sequential=False)
        e1prev_intext = ExtendableField(event_vocab, sequential=True, include_lengths=True) #Bag of previous events in text

        fields = [('e1_text', e1_text), ('e1', e1), ('e2', e2), ('e1prev_intext', e1prev_intext)]
        examples = []
        with open(path, 'r') as f:
            for line in f:
                json_line = json.loads(line)
                e1_text_data = json_line['e1_text'].lower()
                e1_data = json_line['e1']
                e2_data = json_line['e2']
                e1prev_intext_data = json_line['e1prev_intext']

                examples.append(ttdata.Example.fromlist([e1_text_data, e1_data, e2_data, e1prev_intext_data], fields))

        if not filter_unk_events:
            filter_pred = None
        else:
            filter_pred = lambda inst: inst.e1 in event_vocab.stoi and inst.e2 in event_vocab.stoi
 
        super(InstanceDataset, self).__init__(examples, fields, filter_pred=filter_pred)

