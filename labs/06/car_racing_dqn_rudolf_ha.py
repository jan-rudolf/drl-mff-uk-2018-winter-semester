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
import collections
import itertools

import car_racing_evaluator
import numpy as np
import tensorflow as tf


class Network:
	def __init__(self, threads, seed=42):
		# Create an empty graph and a session
		graph = tf.Graph()
		graph.seed = seed
		self.session = tf.Session(graph = graph, config=tf.ConfigProto(inter_op_parallelism_threads=threads,
																		 intra_op_parallelism_threads=threads))

	def construct(self, args, state_shape, num_actions, construct_summary=False):
		self.construct_summary = construct_summary
		with self.session.graph.as_default():
			self.states = tf.placeholder(tf.float32, [None] + state_shape)
			self.actions = tf.placeholder(tf.int32, [None])
			self.q_values = tf.placeholder(tf.float32, [None])

			# Compute the q_values
			if args.cnn is None:
				# preprocess image
				resized_input = tf.image.resize_images(self.states, size=[48, 48])
				grayscale_input = tf.image.rgb_to_grayscale(resized_input)
				flattened_input = tf.layers.flatten(grayscale_input)

				hidden = flattened_input
				for _ in range(args.hidden_layers):
					hidden = tf.layers.dense(hidden, args.hidden_layer_size, activation=tf.nn.relu)
				self.predicted_values = tf.layers.dense(hidden, num_actions, name="output_layer")
			else:
				# preprocess image
				resized_input = tf.image.resize_images(self.states, size=[96, 96])

				cnn_desc = args.cnn.split(',')
				depth = len(cnn_desc)
				layers = [None] * (1 + depth)
				layers[0] = resized_input
				for l in range(depth):
					layer_idx = l + 1
					layer_name = "layer{}-{}".format(l, cnn_desc[l])
					specs = cnn_desc[l].split('-')
					# print("...adding layer {} with specs {}".format(layer_name, specs))
					if specs[0] == 'C':
						# - C-filters-kernel_size-stride-padding: Add a convolutional layer with ReLU activation and
						#   specified number of filters, kernel size, stride and padding. Example: C-10-3-1-same
						layers[layer_idx] = tf.layers.conv2d(inputs=layers[layer_idx - 1], filters=int(specs[1]),
																								 kernel_size=int(specs[2]), strides=int(specs[3]), padding=specs[4],
																								 activation=tf.nn.relu, name=layer_name)
					if specs[0] == 'M':
						# - M-kernel_size-stride: Add max pooling with specified size and stride. Example: M-3-2
						layers[layer_idx] = tf.layers.max_pooling2d(inputs=layers[layer_idx - 1], pool_size=int(specs[1]),
																												strides=int(specs[2]), name=layer_name)
					if specs[0] == 'F':
						# - F: Flatten inputs
						layers[layer_idx] = tf.layers.flatten(inputs=layers[layer_idx - 1], name=layer_name)
					if specs[0] == 'R':
						# - R-hidden_layer_size: Add a dense layer with ReLU activation and specified size. Ex: R-100
						layers[layer_idx] = tf.layers.dense(inputs=layers[layer_idx - 1], units=int(specs[1]), activation=tf.nn.relu,
																								name=layer_name)
				# Store result in `features`.
				features = tf.layers.flatten(inputs=layers[-1], name="flattened_features")
				self.predicted_values = tf.layers.dense(features, num_actions, activation=None, name="output_layer")

			# Training
			if args.reward_clipping:
				deltas = self.q_values - tf.boolean_mask(self.predicted_values, tf.one_hot(self.actions, num_actions))
				clipped_rewards = tf.clip_by_value(
					deltas,
					-1.0,
					+1.0
				)
				self.loss = tf.losses.mean_squared_error(
					clipped_rewards,
					tf.zeros_like(clipped_rewards)
				)
			else:
				self.loss = tf.losses.mean_squared_error(
					self.q_values,
					tf.boolean_mask(self.predicted_values, tf.one_hot(self.actions, num_actions))
				)
			global_step = tf.train.create_global_step()
			self.training = tf.train.AdamOptimizer(args.learning_rate).minimize(self.loss, global_step=global_step, name="training")

			if construct_summary:
				self.summary_writer = tf.contrib.summary.create_file_writer(args.logdir, flush_millis=10 * 1000)
				self.summaries = {}
				with self.summary_writer.as_default(), tf.contrib.summary.always_record_summaries():
					self.summaries["train"] = [tf.contrib.summary.scalar("train/loss", self.loss)]

			# Initialize variables
			self.session.run(tf.global_variables_initializer())
			if construct_summary:
				with self.summary_writer.as_default():
					tf.contrib.summary.initialize(session=self.session, graph=self.session.graph)

	def copy_variables_from(self, other):
		for variable, other_variable in zip(self.session.graph.get_collection(tf.GraphKeys.GLOBAL_VARIABLES),
											other.session.graph.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)):
			variable.load(other_variable.eval(other.session), self.session)

	def predict(self, states):
		return self.session.run(self.predicted_values, {self.states: states})

	def train(self, states, actions, q_values):
		if self.construct_summary:
			loss, _, _ = self.session.run([self.loss, self.training, self.summaries["train"]], {self.states: states, self.actions: actions, self.q_values: q_values})
			return loss
		else:
			self.session.run(self.training, {self.states: states, self.actions: actions, self.q_values: q_values})

if __name__ == "__main__":
		# Fix random seed
		np.random.seed(42)

		# Parse arguments
		import argparse
		parser = argparse.ArgumentParser()
		parser.add_argument("--batch_size", default=8, type=int, help="Batch size.")
		parser.add_argument("--episodes", default=128, type=int, help="Episodes for epsilon decay.")
		parser.add_argument("--epsilon", default=0.3, type=float, help="Exploration factor.")
		parser.add_argument("--epsilon_final", default=0.01, type=float, help="Final exploration factor.")
		parser.add_argument("--gamma", default=1.0, type=float, help="Discounting factor.")
		parser.add_argument("--hidden_layers", default=4, type=int, help="Number of hidden layers.")
		parser.add_argument("--hidden_layer_size", default=256, type=int, help="Size of hidden layer.")
		parser.add_argument("--cnn", default="C-8-3-1-same,C-32-5-1-same,C-128-7-2-same", type=str,
		                    help="Description of the CNN architecture.")
		parser.add_argument("--learning_rate", default=0.001, type=float, help="Learning rate.")
		# TODO implement alpha decay
		parser.add_argument("--alpha", default=None, type=float, help="Learning rate.")
		parser.add_argument("--alpha_final", default=None, type=float, help="Final learning rate.")
		parser.add_argument("--render_each", default=0, type=int, help="Render some episodes.")
		parser.add_argument("--threads", default=1, type=int, help="Maximum number of threads to use.")
		parser.add_argument("--update_every", default=128, type=int, help="Update frequency of target network.")
		parser.add_argument("--replay_buffer_size", default=16384, type=int, help="Maximum size of replay buffer")
		parser.add_argument("--reward_clipping", default=False, type=bool, help="Switch on reward clipping.")
		parser.add_argument("--debug", default=False, type=bool, help="Switch on debug mode.")

		parser.add_argument("--frame_skip", default=16, type=int, help="Repeat actions for given number of frames.")
		# TODO implement frame_history
		parser.add_argument("--frame_history", default=1, type=int, help="Number of past frames to stack together.")

		parser.add_argument("--evaluate", default=False, type=bool, help="Run evaluation phase.")
		args = parser.parse_args()

		# Create logdir name
		if args.debug:
			import datetime
			import os
			args.logdir = "logs/{}-{}-{}".format(
				os.path.basename(__file__),
				datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"),
				",".join(map(lambda arg:"{}={}".format(*arg), sorted(vars(args).items())))
			)
			if not os.path.exists("logs"):
				os.mkdir("logs") # TF 1.6 will do this by itself

		# Create the environment
		env = car_racing_evaluator.environment()
		discrete_steer = [-1, 0, 1]
		discrete_gas = [0, 1]
		discrete_brake = [0, 1]
		discrete_actions = np.array([x for x in itertools.product(discrete_steer, discrete_gas, discrete_brake)])
		action_size = len(discrete_actions)

		# Construct the network
		network = Network(threads=args.threads)
		network.construct(args, env.state_shape, action_size, construct_summary=args.debug)

		# Construct the target network
		target_network = Network(threads=args.threads)
		target_network.construct(args, env.state_shape, action_size)

		# Replay memory; maxlen parameter can be passed to deque for a size limit,
		# which we however do not need in this simple task.
		replay_buffer = collections.deque(maxlen=args.replay_buffer_size)
		Transition = collections.namedtuple("Transition", ["state", "action", "reward", "done", "next_state"])

		evaluating = False
		training_episodes = 2 * args.episodes
		epsilon = args.epsilon
		update_step = 0
		current_loss = None
		best_mean_100ep_return = None
		while True:
			# Perform episode
			state, done = env.reset(evaluating), False
			while not done:
				if args.render_each and (env.episode + 1) % args.render_each == 0:
						env.render()

				# compute action using epsilon-greedy policy.
				if np.random.uniform() > epsilon:
					# You can compute the q_values of a given state:
					q_values = network.predict([state])
					action_index = np.argmax(q_values)
				else:
					action_index = np.random.randint(action_size)
				action = discrete_actions[action_index]

				next_state, reward, done, _ = env.step(action, frame_skip=args.frame_skip)

				# Append state, action, reward, done and next_state to replay_buffer
				replay_buffer.append(Transition(state, action_index, reward, done, next_state))

				# If the replay_buffer is large enough,
				replay_size = len(replay_buffer)
				if replay_size >= args.batch_size:
					# perform a training batch of `args.batch_size` uniformly randomly chosen transitions.
					sampled_indices = np.random.choice(replay_size, args.batch_size, replace=False)

					states = []
					action_indices = []
					rewards = []
					next_states = []
					done_list = []
					for i in sampled_indices:
						transition = replay_buffer[i]
						states.append(transition.state)
						action_indices.append(transition.action)
						rewards.append(transition.reward)
						next_states.append(transition.next_state)
						done_list.append(transition.done)

					if update_step % args.update_every == 0:
						mean_100ep_return = np.mean(env._episode_returns[-100:])
						tolerance = .8
						if (best_mean_100ep_return is None) or (tolerance * best_mean_100ep_return < mean_100ep_return):
							target_network.copy_variables_from(network)
							best_mean_100ep_return = mean_100ep_return
						if args.debug:
							print("[update step #{}] Copying weights to target net...".format(update_step))
					q_values_in_next_states = target_network.predict(next_states)
					estimates_in_next_states = np.multiply(
						args.gamma * np.max(q_values_in_next_states, axis=-1),
						0,
						where=done_list
					)
					q_values = rewards + estimates_in_next_states

					# After you choose `states`, `actions` and their target `q_values`, train the network
					current_loss = network.train(states, action_indices, q_values)
					update_step += 1

				state = next_state

			if args.debug:
				print("Loss: {}".format(current_loss))

			# Decide if we want to start evaluating
			evaluating = env.episode > training_episodes
			early_stop_window = 100
			mean_return = [None] * 3
			if not evaluating and env.episode > early_stop_window + 100:
				mean_return[0] = np.mean(env._episode_returns[- early_stop_window:])
				mean_return[1] = np.mean(env._episode_returns[- early_stop_window - 50:-50])
				mean_return[2] = np.mean(env._episode_returns[- early_stop_window - 100:-100])
				evaluating = mean_return[0] > 400 and mean_return[1] > 400 and mean_return[2] > 400

			if not evaluating:
				if args.epsilon_final:
					epsilon = np.exp(np.interp(env.episode + 1, [0, args.episodes], [np.log(args.epsilon), np.log(args.epsilon_final)]))
			else:
				break

		# Perform last 100 evaluation episodes
		if args.evaluate:
			for _ in range(100):
				state, done = env.reset(start_evaluate=True), False

				while not done:
					q_values = network.predict([state])
					action_index = np.argmax(q_values)                 # greedy
					action = discrete_actions[action_index]
					next_state, _, done, _ = env.step(action, frame_skip=args.frame_skip)
					state = next_state
