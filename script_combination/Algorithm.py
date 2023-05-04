
import os
import copy

import torch
import torch.nn as nn
import torch.nn.functional as F

import numpy as np
from cares_reinforcement_learning.util import helpers as hlp
from skimage.metrics import structural_similarity as ssim



from networks import Actor
from networks import Critic
from networks import Encoder
from networks import Decoder
from networks import EPPM


class Algorithm:

    def __init__(self, latent_size, action_num, device):

        self.latent_size = latent_size
        self.action_num  = action_num
        self.device      = device

        self.gamma = 0.99
        self.tau   = 0.005
        self.ensemble_size = 10

        self.learn_counter      = 0
        self.policy_update_freq = 2

        self.encoder = Encoder(self.latent_size).to(self.device)
        self.decoder = Decoder(self.latent_size).to(self.device)

        self.actor   = Actor(self.latent_size, self.action_num, self.encoder).to(self.device)
        self.critic  = Critic(self.latent_size, self.action_num, self.encoder).to(self.device)

        self.eppm = nn.ModuleList()
        networks = [EPPM(self.latent_size, self.action_num) for _ in range(self.ensemble_size)]
        self.eppm.extend(networks)
        self.eppm.to(self.device)

        self.actor_target  = copy.deepcopy(self.actor)
        self.critic_target = copy.deepcopy(self.critic)

        lr_actor   = 1e-4
        lr_critic  = 1e-3
        self.actor_optimizer   = torch.optim.Adam(self.actor.parameters(),   lr=lr_actor)
        self.critic_optimizer  = torch.optim.Adam(self.critic.parameters(),  lr=lr_critic)

        lr_encoder = 1e-3
        lr_decoder = 1e-3
        self.encoder_optimizer = torch.optim.Adam(self.encoder.parameters(), lr=lr_encoder)
        self.decoder_optimizer = torch.optim.Adam(self.decoder.parameters(), lr=lr_decoder, weight_decay=1e-7)

        lr_eppm      = 1e-4
        w_decay_epp  = 1e-3
        self.eppm_optimizers = [torch.optim.Adam(self.eppm[i].parameters(), lr=lr_eppm, weight_decay=w_decay_epp) for i in range(self.ensemble_size)]


    def get_action_from_policy(self, state, evaluation=False, noise_scale=0.1):
        self.actor.eval()
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).to(self.device)
            state_tensor = state_tensor.unsqueeze(0)
            action = self.actor(state_tensor)
            action = action.cpu().data.numpy().flatten()
            if not evaluation:
                # this is part the TD3 too, add noise to the action
                noise = np.random.normal(0, scale=noise_scale, size=self.action_num)
                action = action + noise
                action = np.clip(action, -1, 1)
        self.actor.train()
        return action

    def get_surprise_rate(self, state, action):

        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).to(self.device)
            state_tensor = state_tensor.unsqueeze(0)

            action_tensor = torch.FloatTensor(action).to(self.device)
            action_tensor = action_tensor.unsqueeze(0)

            predict_mean_set, predict_std_set = [], []

            for network in self.eppm:
                network.eval()
                predicted_distribution = network(state_tensor, action_tensor)

                mean = predicted_distribution.mean
                std = predicted_distribution.stddev

                predict_mean_set.append(mean.detach().cpu().numpy())
                predict_std_set.append(std.detach().cpu().numpy())

            ensemble_means = np.concatenate(predict_mean_set, axis=0)
            ensemble_stds = np.concatenate(predict_std_set, axis=0)

            avr_mean = np.mean(ensemble_means, axis=0)
            avr_std  = np.mean(ensemble_stds, axis=0)

            avr_std_total = np.mean(ensemble_stds)

            return avr_std_total

    def get_novelty_rate(self, state):

        state_tensor_img = torch.FloatTensor(state).to(self.device)
        state_tensor_img = state_tensor_img.unsqueeze(0)

        self.encoder.eval()
        self.decoder.eval()
        with torch.no_grad():
            z_vector = self.encoder(state_tensor_img)
            rec_img = self.decoder(z_vector)

        # todo note that this is a stack of 3 images
        original_stack_imgs  = state_tensor_img.cpu().numpy()[0]
        reconstruction_stack = rec_img.cpu().numpy()[0]

        # this could be better
        ssim_index_1 = ssim(original_stack_imgs[0], reconstruction_stack[0])
        ssim_index_2 = ssim(original_stack_imgs[1], reconstruction_stack[1])
        ssim_index_3 = ssim(original_stack_imgs[2], reconstruction_stack[2])

        avr_ssim_total = (ssim_index_1 + ssim_index_2 + ssim_index_3) / 3

        return avr_ssim_total



    def train_policy(self, experiences):
        self.learn_counter += 1

        states, actions, rewards, next_states, dones = experiences
        batch_size = len(states)

        # Convert into tensor
        states      = torch.FloatTensor(np.asarray(states)).to(self.device)
        actions     = torch.FloatTensor(np.asarray(actions)).to(self.device)
        rewards     = torch.FloatTensor(np.asarray(rewards)).to(self.device)
        next_states = torch.FloatTensor(np.asarray(next_states)).to(self.device)
        dones       = torch.LongTensor(np.asarray(dones)).to(self.device)

        # Reshape to batch_size
        rewards = rewards.unsqueeze(0).reshape(batch_size, 1)
        dones   = dones.unsqueeze(0).reshape(batch_size, 1)

        with torch.no_grad():
            next_actions = self.actor_target(next_states)
            target_noise = 0.2 * torch.randn_like(next_actions)
            target_noise = torch.clamp(target_noise, -0.5, 0.5)
            next_actions = next_actions + target_noise
            next_actions = torch.clamp(next_actions, min=-1, max=1)

            target_q_values_one, target_q_values_two = self.critic_target(next_states, next_actions)
            target_q_values = torch.minimum(target_q_values_one, target_q_values_two)

            q_target = rewards + self.gamma * (1 - dones) * target_q_values

        q_values_one, q_values_two = self.critic(states, actions)

        critic_loss_1 = F.mse_loss(q_values_one, q_target)
        critic_loss_2 = F.mse_loss(q_values_two, q_target)
        critic_loss_total = critic_loss_1 + critic_loss_2

        # Update the Critic
        self.critic_optimizer.zero_grad()
        critic_loss_total.backward()
        self.critic_optimizer.step()

        # Update Autoencoder
        z_vector = self.encoder(states)
        rec_obs  = self.decoder(z_vector)
        rec_loss = F.mse_loss(states, rec_obs)

        latent_loss = (0.5 * z_vector.pow(2).sum(1)).mean()  # add L2 penalty on latent representation
        ae_loss     = rec_loss + 1e-6 * latent_loss

        self.encoder_optimizer.zero_grad()
        self.decoder_optimizer.zero_grad()
        ae_loss.backward()
        self.encoder_optimizer.step()
        self.decoder_optimizer.step()

        # Update Actor
        if self.learn_counter % self.policy_update_freq == 0:
            actor_q_one, actor_q_two = self.critic(states, self.actor(states, detach_encoder=True),  detach_encoder=True)
            actor_q_values = torch.minimum(actor_q_one, actor_q_two)
            actor_loss = -actor_q_values.mean()

            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.actor_optimizer.step()

            # Update target network params
            for target_param, param in zip(self.critic_target.parameters(), self.critic.parameters()):
                target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))

            for target_param, param in zip(self.actor_target.parameters(), self.actor.parameters()):
                target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))


    def train_predictive_model(self, experiences):

        states, actions, _, next_states, _ = experiences

        with torch.no_grad():
            # This is my ground truth value
            # state img --> Encoder -->  zt
            # Next state img --> Encoder --> next zt
            states      = torch.FloatTensor(np.asarray(states)).to(self.device)
            actions     = torch.FloatTensor(np.asarray(actions)).to(self.device)
            next_states = torch.FloatTensor(np.asarray(next_states)).to(self.device)

            latent_state      = self.encoder(states, detach=True)
            latent_next_state = self.encoder(next_states, detach=True)

        for predictive_network, optimizer in zip(self.eppm, self.eppm_optimizers):
            predictive_network.train()

            # Get the Prediction of each model
            prediction_distribution = predictive_network(latent_state, actions)
            loss_neg_log_likelihood = - prediction_distribution.log_prob(latent_next_state)
            loss_neg_log_likelihood = torch.mean(loss_neg_log_likelihood)

            # Update weights and bias
            optimizer.zero_grad()
            loss_neg_log_likelihood.backward()
            optimizer.step()

