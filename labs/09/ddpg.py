#!/usr/bin/env python3
import collections

import numpy as np
import tensorflow as tf

import gym_evaluator

class Network:
	def __init__(self, threads, seed=42):
		# Create an empty graph and a session
		graph = tf.Graph()
		graph.seed = seed
		self.session = tf.Session(graph = graph, config=tf.ConfigProto(inter_op_parallelism_threads=threads,
		                                                               intra_op_parallelism_threads=threads))

	def construct(self, args, state_shape, action_components, action_lows, action_highs):
		with self.session.graph.as_default():
			self.states = tf.placeholder(tf.float32, [None] + state_shape)
			self.actions = tf.placeholder(tf.float32, [None, action_components])
			self.returns = tf.placeholder(tf.float32, [None])

			# Actor
			def actor(inputs):
				# Implement actor network, starting with `inputs` and returning
				# action_components values for each batch example. Usually, one
				# or two hidden layers are employed.
				#
				# Each action_component[i] should be mapped to range
				# [actions_lows[i]..action_highs[i]], for example using tf.nn.sigmoid
				# and suitable rescaling.
				latest_layer = inputs
				for _ in range(2):
					latest_layer = tf.layers.dense(latest_layer, args.hidden_layer, activation=tf.nn.relu)
				outputs = tf.layers.dense(latest_layer, action_components, activation=tf.nn.sigmoid)
				rescaled_outputs = action_lows + (action_highs - action_lows) * outputs
				return rescaled_outputs

			with tf.variable_scope("actor"):
				self.mus = actor(self.states)

			with tf.variable_scope("target_actor"):
				target_actions = actor(self.states)

			# Critic from given actions
			def critic(inputs, actions):
				# Implement critic network, starting with `inputs` and `actions`
				# and producing a vector of predicted returns. Usually, `inputs` are fed
				# through a hidden layer first, and then concatenated with `actions` and fed
				# through two more hidden layers, before computing the returns.
				latest_layer = tf.layers.dense(inputs, args.hidden_layer, activation=tf.nn.relu)
				latest_layer = tf.concat(latest_layer, actions)
				for _ in range(2):
					latest_layer = tf.layers.dense(latest_layer, args.hidden_layer, activation=tf.nn.relu)
				outputs = tf.layers.dense(latest_layer, 1, activation=None)
				return outputs

			with tf.variable_scope("critic"):
				values_of_given = critic(self.states, self.actions)

			with tf.variable_scope("critic", reuse=True):
				values_of_predicted = critic(self.states, self.mus)

			with tf.variable_scope("target_critic"):
				self.target_values = critic(self.states, target_actions)

			# Update ops
			update_target_ops = []
			for target_var, var in zip(tf.global_variables("target_actor") + tf.global_variables("target_critic"),
			                           tf.global_variables("actor") + tf.global_variables("critic")):
				update_target_ops.append(target_var.assign((1.-args.target_tau) * target_var + args.target_tau * var))

			# TODO: Training
			# Define actor_loss and critic_loss and then:
			actor_loss = tf.reduce_sum(
				- action_distribution.log_prob(self.actions),
			) * (self.returns - tf.stop_gradient(self.values))

			critic_loss = tf.losses.mean_squared_error(self.returns, self.values)
			global_step = tf.train.create_global_step()
			# - train the critic (if required, using critic variables only,
			#     by using `var_list` argument of `Optimizer.minimize`)
			critic_train = tf.train.AdamOptimizer(args.learning_rate).minimize(
				critic_loss,
				global_step=global_step,
				var_list=tf.global_variables("critic")
			)
			# - train the actor (if required, using actor variables only,
			#     by using `var_list` argument of `Optimizer.minimize`)
			actor_train = tf.train.AdamOptimizer(args.learning_rate).minimize(
				actor_loss,
				global_step=global_step,
				var_list=tf.global_variables("actor")
			)
			# - update target network variables
			# You can group several operations into one using `tf.group`.
			self.training = tf.group([critic_train, actor_train] + update_target_ops)

			# Initialize variables
			self.session.run(tf.global_variables_initializer())

	def predict_actions(self, states):
		return self.session.run(self.mus, {self.states: states})

	def predict_values(self, states):
		return self.session.run(self.target_values, {self.states: states})

	def train(self, states, actions, returns):
		self.session.run(self.training, {self.states: states, self.actions: actions, self.returns: returns})


class OrnsteinUhlenbeckNoise:
	"""Ornstein-Uhlenbeck process."""

	def __init__(self, shape, mu, theta, sigma):
		self.mu = mu * np.ones(shape)
		self.theta = theta
		self.sigma = sigma
		self.reset()

	def reset(self):
		self.state = np.copy(self.mu)

	def sample(self):
		self.state += self.theta * (self.mu - self.state) + np.random.normal(scale=self.sigma, size=self.state.shape)
		return self.state


if __name__ == "__main__":
	# Fix random seed
	np.random.seed(42)

	# Parse arguments
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument("--batch_size", default=None, type=int, help="Batch size.")
	parser.add_argument("--env", default="Pendulum-v0", type=str, help="Environment.")
	parser.add_argument("--evaluate_each", default=100, type=int, help="Evaluate each number of episodes.")
	parser.add_argument("--evaluate_for", default=10, type=int, help="Evaluate for number of batches.")
	parser.add_argument("--noise_sigma", default=0.2, type=float, help="UB noise sigma.")
	parser.add_argument("--noise_theta", default=0.15, type=float, help="UB noise theta.")
	parser.add_argument("--gamma", default=None, type=float, help="Discounting factor.")
	parser.add_argument("--hidden_layer", default=None, type=int, help="Size of hidden layer.")
	parser.add_argument("--learning_rate", default=None, type=float, help="Learning rate.")
	parser.add_argument("--render_each", default=0, type=int, help="Render some episodes.")
	parser.add_argument("--target_tau", default=None, type=float, help="Target network update weight.")
	parser.add_argument("--threads", default=1, type=int, help="Maximum number of threads to use.")
	args = parser.parse_args()

	# Create the environment
	env = gym_evaluator.GymEnvironment(args.env)
	assert len(env.action_shape) == 1
	action_lows, action_highs = map(np.array, env.action_ranges)

	# Construct the network
	network = Network(threads=args.threads)
	network.construct(args, env.state_shape, env.action_shape[0], action_lows, action_highs)

	# Replay memory; maxlen parameter can be passed to deque for a size limit,
	# which we however do not need in this simple task.
	replay_buffer = collections.deque()
	Transition = collections.namedtuple("Transition", ["state", "action", "reward", "done", "next_state"])

	def evaluate_episode(evaluating=False):
		rewards = 0
		state, done = env.reset(evaluating), False
		while not done:
			if args.render_each and env.episode > 0 and env.episode % args.render_each == 0:
				env.render()

			action = network.predict_actions([state])[0]
			state, reward, done, _ = env.step(action)
			rewards += reward
		return rewards

	noise = OrnsteinUhlenbeckNoise(env.action_shape[0], 0., args.noise_theta, args.noise_sigma)
	while True:
		# Training
		for _ in range(args.evaluate_each):
			state, done = env.reset(), False
			noise.reset()
			while not done:
				# Perform an action and store the transition in the replay buffer
				action = network.predict_actions([state])[0] + noise.sample()
				next_state, reward, done, _ = env.step(action)
				replay_buffer.append(Transition(state, action, reward, done, next_state))
				state = next_state

				# If the replay_buffer is large enough, perform training
				if len(replay_buffer) >= args.batch_size:
					batch = np.random.choice(len(replay_buffer), size=args.batch_size, replace=False)
					states, actions, rewards, dones, next_states = zip(*[replay_buffer[i] for i in batch])
					# Perform the training
					# - estimating returns by reward + (0 if done else args.gamma * next_state_value)
					next_state_values = (1 - dones) *  network.predict_values(next_states)
					estimated_returns = rewards + args.gamma * next_state_values
					network.train(states, actions, estimated_returns)

		# Evaluation
		returns = []
		for _ in range(args.evaluate_for):
			returns.append(evaluate_episode())
		mean_return = np.mean(returns)
		print("Evaluation of {} episodes: {}".format(args.evaluate_for, mean_return))

		if np.mean(mean_return) > -200:
			break

	print("Final 100 evaluation episodes:")
	returns = []
	for _ in range(100):
		returns.append(evaluate_episode(evaluating=True))
	mean_return = np.mean(returns)
	print("Evaluation of final {} episodes: {}".format(100, mean_return))
