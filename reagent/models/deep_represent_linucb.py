# Copyright (c) Facebook, Inc. and its affiliates. All rights reserved.

import logging
from typing import List, Optional

import torch
from reagent.models.fully_connected_network import FullyConnectedNetwork
from reagent.models.linear_regression import batch_quadratic_form, LinearRegressionUCB
from torch import nn

logger = logging.getLogger(__name__)


class DeepRepresentLinearRegressionUCB(LinearRegressionUCB):
    """
    It is a multiple layer regression model that output UCB score.
    The first N layers are trainable by torch optimizer().
    The last layer is the traditional LinUCB, and it is not updated by optimizer,
        but still will be updated by matrix computations.

    Example :
        Features(dim=9) --> deep_represent_layers --> Features(dim=3) --> LinUCB --> ucb score

        DeepRepresentLinUCBTrainer(
        (scorer): DeepRepresentLinearRegressionUCB(
            (deep_represent_layers): FullyConnectedNetwork(
            (dnn): Sequential(
                (0): Linear(in_features=9, out_features=6, bias=True)
                (1): ReLU()
                (2): Linear(in_features=6, out_features=3, bias=True)
                (3): Identity()
            )
            )
        )
        (loss_fn): MSELoss()
        )
    """

    def __init__(
        self,
        raw_input_dim: int,  # raw feature
        sizes: List[int],  # MLP hidden layers of the deep_represent module
        linucb_inp_dim: int,  # output from deep_represent module, i.e., input to LinUCB module
        activations: List[str],
        *,
        predict_ucb: float = True,
        output_activation: str = "linear",
        use_batch_norm: bool = False,
        dropout_ratio: float = 0.0,
        normalized_output: bool = False,
        use_layer_norm: bool = False,
        ucb: Optional[torch.Tensor] = None,
        mlp_out: torch.Tensor = None,  # pyre-fixme; Attribute has type `Tensor`; used as `None`.
        pred_u: torch.Tensor = None,  # pyre-fixme; Attribute has type `Tensor`; used as `None`.
        pred_sigma: torch.Tensor = None,  # pyre-fixme; Attribute has type `Tensor`; used as `None`.
        mlp_layers: nn.Module = None,  # pyre-fixme; Attribute has type `nn.Module`; used as `None`.
    ):
        super().__init__(input_dim=linucb_inp_dim, predict_ucb=predict_ucb)

        assert raw_input_dim > 0, "raw_input_dim must be > 0, got {}".format(
            raw_input_dim
        )
        assert linucb_inp_dim > 0, "linucb_inp_dim must be > 0, got {}".format(
            linucb_inp_dim
        )
        assert len(sizes) == len(
            activations
        ), "The numbers of sizes and activations must match; got {} vs {}".format(
            len(sizes), len(activations)
        )

        self.raw_input_dim = raw_input_dim  # input to DeepRepresent
        self.mlp_out = mlp_out
        self.pred_u = pred_u
        self.pred_sigma = pred_sigma
        if mlp_layers is None:
            self.deep_represent_layers = FullyConnectedNetwork(
                [raw_input_dim] + sizes + [linucb_inp_dim],
                activations + [output_activation],
                use_batch_norm=use_batch_norm,
                dropout_ratio=dropout_ratio,
                normalize_output=normalized_output,
                use_layer_norm=use_layer_norm,
            )
        else:
            self.deep_represent_layers = mlp_layers  # use customized layers

    def input_prototype(self) -> torch.Tensor:
        return torch.randn(1, self.raw_input_dim)

    def forward(
        self, inp: torch.Tensor, ucb_alpha: Optional[float] = None
    ) -> torch.Tensor:
        """
        Pass raw input to mlp.
        This mlp is trainable to optimizer, i.e., will be updated by torch optimizer(),
            then output of mlp is passed to a LinUCB layer.
        """

        self.mlp_out = self.deep_represent_layers(
            inp
        )  # preprocess by DeepRepresent module before fed to LinUCB layer

        if ucb_alpha is None:
            ucb_alpha = self.ucb_alpha
        if not (self.coefs_valid_for_A == self.A).all():
            self._estimate_coefs()
        assert self.predict_ucb is True
        if self.predict_ucb:
            self.pred_u = torch.matmul(self.mlp_out, self.coefs)
            self.pred_sigma = ucb_alpha * torch.sqrt(
                batch_quadratic_form(self.mlp_out, self.inv_A)
            )
            pred_ucb = self.pred_u + self.pred_sigma
            # trainer needs pred_u and mlp_out to update parameters
        else:
            self.pred_u = torch.matmul(self.mlp_out, self.coefs)
            raise Exception(
                "Neural Network LinUCB currently only surport predicting ucb"
            )
        return pred_ucb
