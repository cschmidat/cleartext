import click
import math
import time
from click import Choice

import torch
import torch.nn as nn
import torch.optim as optim
from torchtext.data import Field, BucketIterator

import cleartext.utils as utils
from cleartext.data import WikiSmall
from cleartext.models import EncoderDecoder


# arbitrary choices
EOS_TOKEN = '<eos>'
SOS_TOKEN = '<sos>'
PAD_TOKEN = '<pad>'
UNK_TOKEN = '<unk>'

# fixed choices
BATCH_SIZE = 32
MIN_FREQ = 2
NUM_SAMPLES = 4
CLIP = 1


@click.command()
@click.option('--num_epochs', '-e', default=1, type=int, help='Number of epochs')
@click.option('--max_examples', '-n', default=50_000, type=int, help='Max number of training examples')
@click.option('--embed_dim', '-d', default='50', type=Choice(['50', '100', '200', '300']), help='Embedding dimension')
@click.option('--src_vocab', '-s', default=5_000, type=int, help='Max source vocabulary size')
@click.option('--trg_vocab', '-t', default=2_000, type=int, help='Max target vocabulary size')
@click.option('--rnn_units', '-r', default=100, type=int, help='Number of RNN units')
@click.option('--attn_units', '-a', default=100, type=int, help='Number of attention units')
@click.option('--dropout', '-p', default=0.2, type=float, help='Dropout probability')
def main(num_epochs, max_examples, embed_dim, src_vocab, trg_vocab, rnn_units, attn_units, dropout):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Using {device}')

    # load data
    print('Loading data')
    field_args = {
        'tokenize': 'spacy', 'tokenizer_language': 'en_core_web_sm',
        'init_token': SOS_TOKEN, 'eos_token': EOS_TOKEN, 'pad_token': PAD_TOKEN, 'unk_token': UNK_TOKEN,
        'lower': True, 'preprocessing': utils.preprocess
    }
    SRC = Field(**field_args)
    TRG = Field(**field_args)

    train_data, valid_data, test_data = WikiSmall.splits(fields=(SRC, TRG), max_examples=max_examples)
    print(f'Loaded {len(train_data)} training examples')

    # load embeddings
    print(f'Loading {embed_dim}-dimensional GloVe vectors')
    proj_root = utils.get_proj_root()
    vectors_path = proj_root / '.vector_cache'
    glove = f'glove.6B.{embed_dim}d'
    # todo: fix error when actual vocabulary loaded is less than max size
    vocab_args = {'min_freq': MIN_FREQ, 'vectors': glove, 'vectors_cache': vectors_path}
    SRC.build_vocab(train_data, max_size=src_vocab, **vocab_args)
    TRG.build_vocab(train_data, max_size=trg_vocab, **vocab_args)

    # prepare data
    iters = BucketIterator.splits((train_data, valid_data, test_data), batch_size=BATCH_SIZE, device=device)
    train_iter, valid_iter, test_iter = iters
    print(f'Source vocabulary size: {len(SRC.vocab)}')
    print(f'Target vocabulary size: {len(TRG.vocab)}')

    # build model
    print('Building model')
    model = EncoderDecoder(device, SRC.vocab.vectors, TRG.vocab.vectors, rnn_units, attn_units, dropout).to(device)
    model.apply(utils.init_weights)
    trainable, total = utils.count_parameters(model)
    print(f'Trainable parameters: {trainable} | Total parameters: {total}')

    # prepare optimizer and loss
    optimizer = optim.Adam(model.parameters())
    criterion = nn.CrossEntropyLoss(ignore_index=TRG.vocab.stoi[PAD_TOKEN])

    # start training cycle
    print(f'Training model for {num_epochs} epochs')
    best_valid_loss = float('inf')  # todo: update and use checkpoints
    for epoch in range(num_epochs):
        start_time = time.time()
        train_loss = utils.train_step(model, train_iter, criterion, optimizer)
        valid_loss = utils.eval_step(model, valid_iter, criterion)
        end_time = time.time()

        epoch_mins, epoch_secs = utils.format_time(start_time, end_time)
        print(f'Epoch: {epoch+1:02} | Time: {epoch_mins}m {epoch_secs}s')
        print(f'\tTraining loss: {train_loss:.3f}\t| Training perplexity: {math.exp(train_loss):7.3f}')
        print(f'\tValidation Loss: {valid_loss:.3f}\t| Validation perplexity: {math.exp(valid_loss):7.3f}')

    # run tests
    print('Testing model')
    test_loss = utils.eval_step(model, test_iter, criterion)
    print(f'Test loss: {test_loss:.3f} | Test perplexity: {math.exp(test_loss):7.3f}')

    # print some translation samples
    print('Model sample')
    ignore = list(map(lambda s: TRG.vocab.stoi[s], [UNK_TOKEN, SOS_TOKEN, EOS_TOKEN, PAD_TOKEN]))
    source, output, target = utils.sample(model, test_iter, ignore)
    for i in torch.randint(0, len(source), (NUM_SAMPLES,)):
        print('> ', utils.seq_to_sentence(source.T[i].tolist(), SRC.vocab, [PAD_TOKEN]))
        print('= ', utils.seq_to_sentence(target.T[i].tolist(), TRG.vocab, [PAD_TOKEN]))
        print('< ', utils.seq_to_sentence(output.T[i].tolist(), TRG.vocab, [PAD_TOKEN]))
        print()


if __name__ == '__main__':
    main()