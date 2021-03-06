# Takes in a directory with decompevent.json files, a directory with conll files and outputs a training data file
import sys 
import os
import json
import argparse
from predpatt import PredPatt, load_conllu

#usage: python decomp2train_format.py input.decompevent.json input.txt.conll output.json

def parse_conll_filename(fname): #taken from rrudinger's preprocessing scripts
    fname = fname.rstrip(".conllu")
    fname = fname.split("/")[-1]
    doc_id = ".".join(fname.split(".")[-2::])
    book_file_name = ".".join(fname.split(".")[:-2])
    genre = book_file_name.split(":")[0]
    book = book_file_name.split(":")[1:]
    return genre, book, doc_id

def parse_decomp_filename(fname): #taken from rrudinger's preprocessing scripts
    fname = fname.split(".event.decomp.json")[0]
    book = fname.split(":")[-1]
    genre = fname.split(":")[0].split("/")[-1]
    return genre, book

def predpatt2text(predicate): #Convert predpatt Predicate object to text
    token_list = predicate.tokens
    for arg in predicate.arguments:
        token_list = token_list + arg.tokens
    token_list = sorted(token_list, key=lambda tok: tok.position)
    return " ".join([x.text for x in token_list])


def concat_single_chunk(json_chunk_list): #Convert a list of sentential json obj to a single event chain, in a single dict
    #Filter out the following
    #-Non realis events
    event_chain = []
    event_texts = []
    event_args = []
    for line in json_chunk_list:    
        events = line['syntactic-events']
        texts = line['event_text']
        fact = line['fact-predictions']
        pheads=line['predicate-head-idxs']
        args = line['args']
        assert len(pheads) == len(texts) and len(args) == len(texts) and len(texts) <= len(events)  #Single predicate sometimes expanded into multiple predicates, in this case, just take the first event

        for i in range(len(texts)):
            if fact[i] == "pos":
                event_chain.append(events[i])
                event_texts.append(texts[i])
                event_args.append(args[i])

    assert len(event_chain) == len(event_texts) == len(event_args)
    outdict = {"event_chain":event_chain, "event_texts":event_texts, "event_args":event_args}
    return outdict
            

def convert_to_train(concat_chunk, file_id, include_context=False, max_context_size=10): #convert a single connll chunk (output of concat_single_chunk) into individual training instances
    instances = []
    for i in range(len(concat_chunk['event_chain'])-1):
        event_1 = concat_chunk['event_chain'][i]
        event_2 = concat_chunk['event_chain'][i+1]
        text_1 = concat_chunk['event_texts'][i]
        event_1_arg = concat_chunk['event_args'][i]

        event_prev_text = concat_chunk['event_chain'][:i][-max_context_size:] if include_context else [] #only take previous max_context_size
        event_prev_text_nodup = [i for n, i in enumerate(event_prev_text) if i not in event_prev_text[:n]] #remove duplicates

        instances.append({'e1':event_1, 'e2':event_2, 'e1_text':text_1, 'e1prev_intext':event_prev_text_nodup, 'id':file_id+str(i), 'e1arg':event_1_arg})
    return instances
        


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='EventSpansScrip')
    parser.add_argument('--decompdir', type=str, help='Directory with decomp event json files' )
    parser.add_argument('--conlldir', type=str, help='Directory with conll files of data')
    parser.add_argument('--outfile', type=str)
    parser.add_argument('--include_context', action='store_true', help='Whether or not to include the previous events in chain')
    parser.add_argument('--max_context_size', type=int, default=10)
    args = parser.parse_args()


    decompdir = args.decompdir.rstrip("/")
    conlldir= args.conlldir.rstrip("/")
    outfile = args.outfile

    output_writer = open(outfile, 'w')

    num_books = len(os.listdir(decompdir))
    num_processed = 0
    num_skipped = 0

    for decompfi in os.listdir(decompdir): #For each book
        decompfile = os.path.join(decompdir, decompfi)
        with open(decompfile, 'r') as decomp_fi:
            decomp_lines = decomp_fi.readlines()
   
        currgenre, currbook = parse_decomp_filename(decompfile)
        print("Processing {} of Genre: {}, Progress {}/{} ({} %), Num Skipped: {}".format(currbook, currgenre, num_processed, num_books, num_processed/(num_books*1.0), num_skipped))
        
        decomp_lines_json = [json.loads(x) for x in decomp_lines]

        book_conll_files = [fi for fi in os.listdir(conlldir) if parse_conll_filename(fi)[1][0] == currbook]

        for conllfi in book_conll_files: #For each chunk in the book
            conllfile = os.path.join(conlldir, conllfi)
            genre, book, doc_id = parse_conll_filename(conllfile)
            conll_iter = load_conllu(conllfile)
            decomp_lines_json_chunk = [x for x in decomp_lines_json if x['doc-id']==doc_id] #get the lines associated with this chunk
            line_idx = 0 #Where we are in the decomp json file

            valid_instance = True
            for sent_id, parse in conll_iter:
                sent_id = int(sent_id.split('_')[1])

                if line_idx >= len(decomp_lines_json_chunk):
                    break

                if decomp_lines_json_chunk[line_idx]['sent-id'] == sent_id: #check if there is a matching decomp extraction for this conll line
                    json_line = decomp_lines_json_chunk[line_idx]
                    ppat = PredPatt(parse)
                    pred_heads = json_line['predicate-head-idxs']
                    pred_args = json_line['pred-args']
                    assert len(pred_heads) <= len(pred_args)
                    event_text = []
                    event_args = []
                    for idx, head in enumerate(pred_heads):
                        head_args = [x for x in pred_args if x[0] == head]
                        assert len(head_args) > 0
                        head_arg_id = head_args[0][1]
                        if head < len(ppat.tokens) and ppat.tokens[head] in ppat.event_dict.keys() and head_arg_id < len(ppat.tokens):
                            predicate = ppat.event_dict[ppat.tokens[head]]
                            pred_text = predpatt2text(predicate)
                            event_text.append(pred_text)
                            event_args.append(ppat.tokens[head_arg_id].text)
                        else:
                            valid_instance = False
                            num_skipped += 1
                    json_line['event_text'] = event_text
                    json_line['args'] = event_args
                    json_line['sprl-predictions'] = []
                    line_idx += 1
                        
            
            if valid_instance: #Write instances for this chunk
                file_id = genre + "-" + book[0] + "-" + doc_id + "_"
                instances = convert_to_train(concat_single_chunk(decomp_lines_json_chunk), file_id, include_context=args.include_context, max_context_size=args.max_context_size)

                for inst in instances:
                    json.dump(inst, output_writer)
                    output_writer.write('\n')
            else:
                print("Skipping due to PredPatt Error")

        num_processed +=1  #finished processing book

    output_writer.close()
    


            
            
