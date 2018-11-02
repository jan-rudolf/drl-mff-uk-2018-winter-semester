#!/usr/bin/env python3
#
# All team solutions **must** list **all** members of the team.
# The members must be listed using their ReCodEx ids anywhere
# in the first comment block in the source file, i.e., in the first
# consecutive range of lines beginning with `#`.
#
# You can find out ReCodEx id on URL when watching ReCodEx profile.
# The id has the following format: 01234567-89ab-cdef-0123-456789abcdef.
#
# 090fa5b6-d3cf-11e8-a4be-00505601122b (Jan Rudolf)
# 08a323e8-21f3-11e8-9de3-00505601122b (Karel Ha)
#

import numpy as np
import gym

if __name__ == "__main__":
	# Fix random seed
	np.random.seed(42)

	# Parse arguments
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument("--episodes", default=1000, type=int, help="Training episodes.")
	args = parser.parse_args()

	# Create the environment
	env = gym.make("FrozenLake-v0")
	env.seed(42)
	states = env.observation_space.n
	actions = env.action_space.n

	# Behaviour policy is uniformly random.
	# Target policy uniformly chooses either action 1 or 2.
	V = np.zeros(states)
	Q = np.zeros((states, actions,))    # TODO make Q 2D: (state, action)
	C = np.zeros((states, actions,))    # TODO make C 2D: (state, action)

	for _ in range(args.episodes):
		state, done = env.reset(), False

		# Generate episode
		episode = []
		while not done:
			action = np.random.choice(actions)
			next_state, reward, done, _ = env.step(action)
			episode.append((state, action, reward))
			state = next_state

		# TODO: Update Q using weighted importance sampling.
		G = 0
		W = 1

		# episode = episode[:-1]

		for episode_sample in reversed(episode):
			state, action, reward = episode_sample
			G = G + reward
			C[state][action] += W  # TODO update this as 2D
			Q[state][action] += (W / C[state][action]) * (G - Q[state][action])  # TODO update this as 2D

			# from https://github.com/openai/gym/blob/master/gym/envs/toy_text/frozen_lake.py
			# LEFT = 0
			# DOWN = 1
			# RIGHT = 2
			# UP = 3

			if action == 1 or action == 2:
				W = W * (0.5/0.25)
			else:
				break
			# W = W * (target_policy/0.25)
			# W = W * (1/target_policy)
			# W = W * (den/num)


	# TODO compute V from Q (as sum); target policy = \pi, lect 2, slide 3
	for i in range(states):
		V[i] = 0.5 * Q[i][1] + 0.5 * Q[i][2] + 0.5 * Q[i][0] + 0.5 * Q[i][3]
		# V[i] = np.max(Q[i])
		# V[i] = 0.25 * Q[i][1] + 0.25 * Q[i][2]
		# V[i] = 0.25 * Q[i][1] + 0.25 * Q[i][2] + 0.25 * Q[i][0] + 0.25 * Q[i][3]
		# V[i] = 0.5 * Q[i][1]  + 0.5 * Q[i][2]

	# Print the final value function V
	for row in V.reshape(4, 4):
		print(" ".join(["{:5.2f}".format(x) for x in row]))
