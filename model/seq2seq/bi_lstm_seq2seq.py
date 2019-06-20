import numpy as np

import torch
from torch import nn
from torch.nn import Embedding, Linear, CrossEntropyLoss

from model.modules.rnn import BiLSTM, BiLSTMCell

from configs.constants import RANDOM_SEED

np.random.seed(RANDOM_SEED)


class BiLSTMEncoder(nn.Module):
    def __init__(self, vocab_size, embedding_size, hidden_size, pad_idx=0, num_layers=1, dropout=0.):
        super(BiLSTMEncoder, self).__init__()
        self.pad_idx = pad_idx

        self.embedding = Embedding(vocab_size, embedding_size, padding_idx=self.pad_idx)
        self.encoder = BiLSTM(embedding_size, hidden_size, num_layers=num_layers, dropout=dropout)

    def forward(self, inputs: torch.Tensor):
        mask = inputs.ne(self._pad_idx).float()
        emb_layer = self.embedding(inputs)
        lstm_outputs, last_hidden = self.encoder(emb_layer, mask)

        return lstm_outputs, last_hidden


class BiLSTMDecoder(nn.Module):
    def __init__(self, vocab_size, embedding_size, hidden_size, pad_idx=0, num_layers=1, dropout=0.):
        super(BiLSTMDecoder, self).__init__()
        self.pad_idx = pad_idx

        self.embedding = Embedding(vocab_size, embedding_size, padding_idx=self.pad_idx)
        self.decoder_cell = BiLSTMCell(embedding_size, hidden_size, num_layers=num_layers, dropout=dropout)
        self.output_linear = Linear(hidden_size * 2, vocab_size)

    def forward(self, inputs: torch.Tensor, hidden_state: [torch.Tensor, torch.Tensor]):
        emb_layer = self.embedding(inputs)
        lstm_outputs, next_hidden_state = self.decoder_cell(emb_layer, hidden_state)
        outputs = self.output_linear(lstm_outputs)

        return outputs, next_hidden_state


class BiLSTMSeq2Seq(nn.Module):
    def __init__(self, encoder: BiLSTMEncoder, decoder: BiLSTMDecoder, bos_idx=1, eos_idx=2, teacher_force_rate=0.7):
        super(BiLSTMSeq2Seq, self).__init__()

        self.teacher_force_rate = teacher_force_rate

        self.bos_idx = bos_idx
        self.eos_idx = eos_idx

        self.encoder = encoder
        self.decoder = decoder

        self.ce_loss = CrossEntropyLoss()

    def forward(self, inputs: torch.Tensor, max_seq_len: int = 20):
        batch_size = inputs.size(0)

        if batch_size > 1:
            raise ValueError('input batch size should be 1.')

        encoder_outputs, encoder_hidden = self.encoder(inputs)

        decoder_hidden = encoder_outputs

        decoder_input = torch.new_full((batch_size, 1), self.bos_idx)
        decoded_sequence = list()

        for i in range(max_seq_len):
            if decoder_input.cpu().tolist()[0] == self.eos_idx:
                break

            decoder_output, next_decoder_hidden = self.decoder(decoder_input, decoder_hidden)
            decoded_label = torch.argmax(decoder_output, dim=-1)
            decoded_sequence.append(decoded_label)

            decoder_input = decoded_label
            decoder_hidden = next_decoder_hidden

        output_seq = torch.stack(decoded_sequence, dim=1)

        return output_seq

    def loss(self, inputs: torch.Tensor, targets: torch.Tensor):
        target_seq_len = targets.size(1)
        target_mask = targets.ne(self.decoder.pad_idx).float()

        encoder_outputs, encoder_hidden = self.encoder(inputs)

        decoder_hidden = encoder_outputs

        decoder_input = targets[:, 0]
        loss = list()

        for i in range(1, target_seq_len-1):
            decoder_output, next_decoder_hidden = self.decoder(decoder_input, decoder_hidden)
            decoded_label = torch.argmax(decoder_output, dim=-1)
            step_loss = self.ce_loss(decoder_output, targets[:, i+1])
            loss.append(step_loss)

            decoder_input = targets[:, i] if self.teacher_force() else decoded_label
            decoder_hidden = next_decoder_hidden

        loss = torch.stack(loss, dim=1) * target_mask
        loss = torch.mean(loss, 1)

        return loss

    def teacher_force(self):
        return self.teacher_force_rate > np.random.rand(1)[0]