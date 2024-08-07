import numpy as np
import json
import codecs
import string

try:
    ascii_letters=string.letters
except:
    ascii_letters = string.ascii_letters

import math

class Encoder(object):
    loaders = {
        "tsv": (lambda x: dict([(int(l.split("\t")[0]), "".join(l.split("\t")[1:])) for l in x.strip().split("\n")])),
        "json": lambda x: json.loads(x),
    }
    def __init__(self, code_2_utf={}, loader_file_contents="", loader="",is_dictionary=False,dict_is_encoder=True,add_null=True):
        if loader == "":
            self.code_2_utf = code_2_utf
        else:
            self.code_2_utf = Encoder.loaders[loader](loader_file_contents)
        self.utf_2_code = {v: k for k, v in self.code_2_utf.items()}
        self.default_utf = "."
        self.default_code = max(self.code_2_utf.keys())
        self.is_dictionary=is_dictionary
        self.dict_is_encoder=dict_is_encoder
        self.contains_null = False
        if add_null:
            self.add_null()

    def __getitem__(self, item):
        if isinstance(item, str):
            return self.utf_2_code[item]
        else: # shuold be int
            return self.code_2_utf[item]

    def __len__(self):
        return max(self.code_2_utf.keys())+1

    def __contains__(self, item):
        if isinstance(item, str):
            return self.utf_2_code.contains(item)
        else: # should be int
            return self.code_2_utf.contains(item)

    def add_null(self, symbol="\u2205"):
        if not self.contains_null:
            self.null_idx = max(self.code_2_utf.keys()) + 1
            self.code_2_utf[self.null_idx] = symbol
            self.utf_2_code = {v: k for k, v in self.code_2_utf.items()}
            self.contains_null = True

    def get_tsv_string(self):
        if self.contains_null:
            return "\n".join(["{}\t{}".format(k,v) for k,v in sorted(self.code_2_utf.items()) if k != self.null_idx])
        else:
            return "\n".join(["{}\t{}".format(k, v) for k, v in sorted(self.code_2_utf.items())])

    @property
    def alphabet_size(self):
        return len(self.code_2_utf)

    @classmethod
    def load_tsv(cls,fname,is_dictionary=False,add_null=True):
        tsv=codecs.open(fname,"r","utf-8").read().strip()
        code_2_utf=dict([(int(l[:l.find("\t")]), "".join(l.split("\t")[1:])) for l in tsv.split("\n")])
        encoder=cls(code_2_utf=code_2_utf,is_dictionary=is_dictionary,add_null=add_null)
        return encoder

    @classmethod
    def load_tsv_str(cls,tsv_str,is_dictionary=False):
        tsv_str=tsv_str.strip()
        code_2_utf=dict([(int(l[:l.find("\t")]), "".join(l.split("\t")[1:])) for l in tsv_str.split("\n")])
        encoder=cls(code_2_utf=code_2_utf,is_dictionary=is_dictionary)
        return encoder

    @classmethod
    def load_json(cls,fname,is_dictionary=False):
        code_2_utf=json.loads(codecs.open(fname,"r","utf-8").read())
        encoder=cls(code_2_utf=code_2_utf,is_dictionary=is_dictionary)
        return encoder


    def encode(self, msg_string):
        if self.is_dictionary:
            return np.array([self.utf_2_code.get(word, self.default_code) for word in msg_string.split() if len(word)>0], dtype="int64")
        else:
            return np.array([self.utf_2_code.get(char, self.default_code) for char in msg_string], dtype="int64")

    def encode_onehot(self,msg_string):
        res=np.zeros([len(msg_string),self.alphabet_size])
        res[np.arange(len(msg_string)),self.encode(msg_string)]=1
        return res

    def decode(self, msg_nparray):
        if self.is_dictionary:
            return " ".join([self.code_2_utf.get(code, self.default_utf) for code in msg_nparray.tolist()])
        else:
            return "".join([self.code_2_utf.get(code, self.default_utf) for code in msg_nparray.tolist()])

    def decode_ctc(self, msg_nparray, null_val=-1):
        if null_val<0:
            null_val=self.null_idx
        keep_idx = np.zeros(msg_nparray.shape, dtype="bool")
        if msg_nparray.size == 0:
            return ""
        keep_idx[0] = msg_nparray[0] != self.null_idx
        keep_idx[1:] = msg_nparray[1:] != msg_nparray[:-1]
        keep_idx = np.logical_and(keep_idx, msg_nparray != null_val)
        if self.is_dictionary:
            return " ".join([self.code_2_utf.get(code, self.default_utf) for code in msg_nparray[keep_idx].tolist()])
        else:
            return "".join([self.code_2_utf.get(code, self.default_utf) for code in msg_nparray[keep_idx].tolist()])

    def encode_batch(self, msg_list):
        res_lengths = np.array([len(msg) for msg in msg_list], dtype="int64")
        res = np.zeros([len(msg_list), res_lengths.max()], dtype="int64")
        count = 0
        for msg_string in msg_list:
            res[count, :len(msg_string)] = self.encode(msg_string)
            count += 1
        return res, res_lengths

    def decode_batch(self, msg_nparray, lengths=None):
        if lengths is None:
            lengths = np.ones(msg_nparray.shape[0],dtype="int32") * msg_nparray.shape[1]
        res = []
        for k in range(msg_nparray.shape[0]):
            res.append(self.decode(msg_nparray[k, :lengths[k]]))
        return res

    def decode_n_levels(self, msg_nparray, lengths=None, n=10):
        """
        Decode all candidate outputs for every position in the batch (in columns, with highest degree of confidence in top position of each column)

        Args:
            msg_array (np.array): batch of sequences, whose elements are raw probs
            lengths (list): lengths of sequences
            n (int): number of candidates to keep for each position (default: 10)

        Returns:
            list: a list of arrays, one per sample, of the form
                    [ [ <sequence of rank-1 characters=CTC output> ],
                      [ <sequence of rank-2 characters> ],
                      ...
                    ]
                where each element of a sequence is a pair (char, prob)
        """
        if lengths is None:
            lengths = np.ones(msg_nparray.shape[0],dtype="int32") * msg_nparray.shape[1]
        
        ordered_probs_nparray = np.sort(msg_nparray, axis=2)
        index_nparray = msg_nparray.argsort(axis=2)

        sequences = []
        # for each string in the batch (length=lengths[k])
        for k in range(msg_nparray.shape[0]):
            char_sequence, prob_sequence = [], []
            # for each time t in the sequence, look at n most probable chars
            for indexes, probs in zip( index_nparray[k, :lengths[k]], ordered_probs_nparray[k, :lengths[k]] ):
                #print("reversed probs = ", [ p for p in np.flip(probs[-n:]) ])
                char_sequence.append( [ self.code_2_utf.get(c, self.default_utf) for c in np.flip(indexes[-n:]) ] )
                prob_sequence.append( np.flip(probs[-n:]) ) 
                #print("char_sequence", np.array(char_sequence).shape)
                #print("prob_sequence", np.array(prob_sequence).shape)
            sequences.append( ( np.array(char_sequence).transpose(1,0), np.array(prob_sequence).transpose(1,0) ) )
        # most probable in top row (instead of leftmost column)
        return sequences

        
    def decode_n_levels1(self, msg_nparray, lengths=None, n=10):
        """
        Decode all candidate outputs for every position in the batch (in columns, with highest degree of confidence in top position of each column)

        Args:
            msg_array (np.array): batch of sequences, whose elements are raw probs
            lengths (list): lengths of sequences
            n (int): number of candidates to keep for each position (default: 10)

        Returns:
            list: a list of arrays, one per sample, of the form
                    [ [ <sequence of rank-1 characters=CTC output> ],
                      [ <sequence of rank-2 characters> ],
                      ...
                    ]
                where each element of a sequence is a pair (char, prob)
        """
        if lengths is None:
            lengths = np.ones(msg_nparray.shape[0],dtype="int32") * msg_nparray.shape[1]
        
        ordered_probs_nparray = np.sort(msg_nparray, axis=2)
        index_nparray = msg_nparray.argsort(axis=2)

        res = []
        # for each string in the batch (length=lengths[k])
        for k in range(msg_nparray.shape[0]):
            #print("Length: ", lengths[k])
            s = []
            # for each time t in the sequence, look at n most probable chars
            for indexes, probs in zip( index_nparray[k, :lengths[k]], ordered_probs_nparray[k, :lengths[k]] ):
                #print("reversed probs = ", [ p for p in reversed(probs[-n:]) ])
                decoded = [ ( self.code_2_utf.get(c, self.default_utf), p) for (c, p) in zip( reversed(indexes[-n:]), reversed(probs[-n:]) ) ]
                s.append( decoded )
            #res.append( np.array(s).transpose(1,0,2) )
            #print(np.array(s).shape)
            print(np.array(s).transpose(1,2,0).shape)
            res.append( np.array(s).transpose(1,2,0) )
            #print(res[-1].shape)
        # most probable in top row (instead of leftmost column)
        return res


    def decode_ctc_batch(self, msg_nparray, null_val, lengths=None):
        if lengths is None:
            lengths = np.ones(msg_nparray.shape[0]) * msg_nparray.shape[1]
        res = []
        for k in range(msg_nparray.shape[0]):
            res.append(self.decode_ctc(msg_nparray[k, :lengths[k]], null_val))
        return res

    def get_encoder(self):
        return lambda x: self.encode(x)

    def get_decoder(self):
        return lambda x: self.decode(x)

    def get_ctc_decoder(self):
        return lambda x: self.decode_ctc(x)

    def __get_phoc_part(self,msg_nparray,partition,nb_partitions):
        range_begin,range_end=msg_nparray.size*float(partition)/nb_partitions,msg_nparray.size*float(partition+1)/nb_partitions
        range_begin_floor = int(math.floor(range_begin))
        range_end_ceil = int(math.ceil(range_end))
        coeffs=np.zeros(msg_nparray.shape)
        coeffs[range_begin_floor+1:range_end_ceil-1]=1
        coeffs[range_begin_floor] = 1.0-(range_begin-range_begin_floor)
        coeffs[range_end_ceil-1]=1.0-(range_end_ceil-range_end)
        result = np.bincount(msg_nparray,coeffs,minlength=len(self))
        return result

    def get_phoc(self,msg,pyramid):
        if not isinstance(msg,np.ndarray):#assume string-like
            msg=self.encode(msg)
        res=[]
        for partition_count in pyramid:
            for partition in range(partition_count):
                res.append(self.__get_phoc_part(msg,partition,partition_count))
        res = np.concatenate(res,axis=0)
        res[res>1]=1.0
        return res



alphanumeric_encoder = Encoder(loader = "tsv", loader_file_contents = "\n".join(
    [str(n) + '\t' + s for n, s in list(enumerate('\u2205' + ascii_letters + string.digits))]))


letter_encoder = Encoder(loader = "tsv", loader_file_contents = "\n".join(
    [str(n) + '\t' + s for n, s in list(enumerate('\u2205' + ascii_letters))]))


def get_int_2_uc_dict(map_tsv, separator=None):
    try:
        map_tsv = open(map_tsv).read().decode("utf8").strip()
    except IOError:
        map_tsv = map_tsv.strip()
    lines = [line.split("\t")[0] for line in map_tsv.split(separator)]
    try:
        code2uc = {int(line[0]): str(line[1]) for line in lines}
    except IndexError:
        code2uc = {counter: str(line[0]) for counter, line in enumerate(lines)}
    return code2uc
