
import torch
import random
import logging
import numpy as np
from argparse import ArgumentParser


from Plot import Plot
from TD3_Autoencoder import TD3
from MemoryBuffer import MemoryBuffer
from two_finger_gripper_env import GripperEnvironment

import matplotlib.pyplot as python_plot # todo try to include this in a better place

logging.basicConfig(level=logging.INFO)

def set_seeds(seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

def parse_args():
    parser = ArgumentParser()

    parser.add_argument("--G",               type=int,  default=10)
    parser.add_argument("--seed",            type=int,  default=5719)
    parser.add_argument("--batch_size",      type=int,  default=100)
    parser.add_argument("--buffer_capacity", type=int,  default=100_000)

    parser.add_argument("--train_episode_num",      type=int, default=5000)
    parser.add_argument("--episode_horizont",       type=int, default=20)
    parser.add_argument("--max_exploration_steps",  type=int, default=2000)   # 3k - 5k Steps


    parser.add_argument('--train_mode', type=str, default='autoencoder')

    parser.add_argument('--usb_port',   type=str, default='/dev/ttyUSB1') # '/dev/ttyUSB1', '/dev/ttyUSB0'
    parser.add_argument('--robot_id',   type=str, default='RR')  # RR, RL
    parser.add_argument('--camera_id',  type=int, default=0)  # 0, 2
    parser.add_argument('--num_motors', type=int, default=4)
    parser.add_argument('--latent_dim', type=int, default=50)

    parser.add_argument('--plot_freq',  type=int, default=10)

    return parser.parse_args()


def train(args, agent, memory, env, act_dim, file_name, plt):
    total_step_counter = 0
    historical_reward  = {"episode": [], "reward": []}


    for episode in range(0, args.train_episode_num):
        step = 0
        episode_reward = 0

        state = env.reset()
        done = False

        for step in range(0, args.episode_horizont):
            print("\n")
            logging.info(f"Taking step {step + 1}/{args.episode_horizont}")
            total_step_counter += 1

            if total_step_counter < args.max_exploration_steps:
                logging.info(f"Running Exploration Steps {total_step_counter}/{args.max_exploration_steps}")
                action = agent.action_sample()
            else:
                action = agent.select_action(state)
                noise  = np.random.normal(0, scale=0.1, size=act_dim)
                action = action + noise
                action = np.clip(action, -1, 1)
                action = action.tolist()

            logging.info(f"Action: {action}")

            next_state, reward, done, truncated = env.step(action)
            memory.add(state, action, reward, next_state, done)
            state = next_state

            episode_reward += reward

            if len(memory.buffer) >= args.max_exploration_steps:
                logging.info("Training Network \n")
                for _ in range(0, args.G):
                    experiences = memory.sample(args.batch_size)
                    agent.learn(experiences)
            if done:
                break

        plt.post(episode_reward)
        historical_reward["episode"].append(episode)
        historical_reward["reward"].append(episode_reward)
        logging.info(f"Episode {episode} was completed with {step + 1} actions taken and a Reward= {episode_reward:.3f}\n")

    agent.save_models(file_name)
    plt.save_plot(file_name)
    plt.save_csv(file_name)
    plt.plot()


def evaluation_function(agent, env, device, file_name):
    evaluation_seed = 123
    set_seeds(evaluation_seed)
    logging.info("Evaluating  Autoencoder")

    # evaluate the encoder-decoder
    _ = env.reset()
    action = agent.action_sample()
    state, _, _, _ = env.step(action)

    state_image_tensor = torch.FloatTensor(state)
    state_image_tensor = state_image_tensor.unsqueeze(0).to(device)

    with torch.no_grad():
        z_vector = agent.critic.encoder_net(state_image_tensor)
        rec_obs  = agent.decoder(z_vector)
        rec_obs  = rec_obs.cpu().numpy()

    input_image     = state[2]
    rec_input_image = rec_obs[0][2]

    python_plot.figure(2)

    python_plot.subplot(1, 2, 1)
    python_plot.title("Image Input")
    python_plot.grid(visible=None)
    python_plot.imshow(input_image, cmap='gray')

    python_plot.subplot(1, 2, 2)
    python_plot.title("Image Reconstruction")
    python_plot.grid(visible=None)
    python_plot.imshow(rec_input_image, cmap='gray')

    python_plot.savefig(f"figures/image_reconstruction_{file_name}.png")
    logging.info("image reconstruction has been saved")



def main():

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    args   = parse_args()
    set_seeds(args.seed)

    act_dim = args.num_motors
    obs_dim = args.latent_dim  # latent dimension

    file_name = f"TD3_mode_{args.train_mode}_seed_{args.seed}_{args.robot_id}"

    env    = GripperEnvironment(args.num_motors, args.camera_id, args.usb_port, args.train_mode)
    memory = MemoryBuffer(args.buffer_capacity)
    td3    = TD3(device, obs_dim, act_dim)
    plt    = Plot(title=file_name, plot_freq=args.plot_freq)

    train(args, td3, memory, env, act_dim, file_name, plt)
    #evaluation_function(td3, env, device, file_name)


if __name__ == '__main__':
    main()