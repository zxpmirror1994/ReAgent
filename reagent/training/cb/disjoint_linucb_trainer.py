#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates. All rights reserved.
import logging
from typing import List, Optional

import torch
from reagent.core.configuration import resolve_defaults
from reagent.core.types import CBInput
from reagent.gym.policies.policy import Policy
from reagent.models.disjoint_linucb_predictor import DisjointLinearRegressionUCB
from reagent.training.reagent_lightning_module import ReAgentLightningModule


logger = logging.getLogger(__name__)


class DisjointLinUCBTrainer(ReAgentLightningModule):
    """
    The trainer for Disjoint LinUCB Contextual Bandit model.
    The model estimates a ridge regression (linear) and only supports dense features.

    Args:
        policy: The policy to be trained. Its scorer has to be DisjointLinearRegressionUCB
    """

    @resolve_defaults
    def __init__(
        self,
        policy: Policy,
        automatic_optimization: bool = False,  # turn off automatic_optimization because we are updating parameters manually
    ):
        super().__init__(automatic_optimization=automatic_optimization)
        assert isinstance(
            policy.scorer, DisjointLinearRegressionUCB
        ), "DisjointLinUCBTrainer requires the policy scorer to be DisjointLinearRegressionUCB"
        self.scorer = policy.scorer
        self.num_arms = policy.scorer.num_arms

    def configure_optimizers(self):
        # no optimizers bcs we update weights manually
        return None

    def update_params(
        self,
        arm_idx: int,
        x: torch.Tensor,
        y: Optional[torch.Tensor],
        weight: Optional[torch.Tensor] = None,
    ):
        """
        Update A and b for arm with index arm_idx
        Args:
            arm_idx: the index of the arm to be updated
            x: 2D tensor of shape (batch_size, dim)
            y: 2D tensor of shape (batch_size, 1)
            weight: 2D tensor of shape (batch_size, 1)
        """
        # weight is number of observations represented by each entry
        if weight is None:
            weight = torch.ones_like(torch.tensor(y))
        weight = weight.float()

        self.scorer.A[arm_idx] += torch.matmul(x.t(), x * weight)  # dim (DA*DC, DA*DC)
        self.scorer.b[arm_idx] += torch.matmul(
            x.t(), y * weight
        ).squeeze()  # dim (DA*DC,)

    def _check_input(self, batch: List[CBInput]):
        # TODO: check later with train_script for batch's dataset info
        assert len(batch) == self.num_arms
        for sub_batch in batch:
            assert sub_batch.context_arm_features.ndim == 2
            assert sub_batch.reward is not None

    def training_step(
        self, batch: List[CBInput], batch_idx: int, optimizer_idx: int = 0
    ):
        """
        each element in batch is a sub-batch of data for that arm
        """
        self._check_input(batch)
        for arm_idx in range(self.num_arms):
            sub_batch = batch[arm_idx]
            self.update_params(
                arm_idx,
                sub_batch.context_arm_features,
                sub_batch.reward,
                sub_batch.weight,
            )

    def on_train_epoch_end(self):
        super().on_train_epoch_end()
        # at the end of the training epoch calculate the coefficients
        self.scorer._estimate_coefs()