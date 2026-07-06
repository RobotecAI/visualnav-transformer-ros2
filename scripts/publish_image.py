import argparse

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from PIL import Image as PILImage
from rclpy.node import Node
from sensor_msgs.msg import Image

from visualnav_transformer.deployment.src.topic_names import IMAGE_TOPIC


class ImagePublisherNode(Node):
    def __init__(self, image_path: str, fps: float):
        super().__init__("image_publisher")
        self.publisher_ = self.create_publisher(Image, IMAGE_TOPIC, 10)
        self.timer = self.create_timer(1.0 / fps, self.publish_image)
        self.bridge = CvBridge()

        pil_image = PILImage.open(image_path)
        self.cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    def publish_image(self):
        # Add slight gaussian noise so consecutive frames differ, like a real camera
        noise = np.random.normal(0, 5, self.cv_image.shape)
        noisy_image = np.clip(self.cv_image.astype(np.int16) + noise, 0, 255).astype(
            np.uint8
        )

        ros_image = self.bridge.cv2_to_imgmsg(noisy_image, encoding="bgr8")
        self.publisher_.publish(ros_image)
        self.get_logger().info("Publishing image")


def main():
    parser = argparse.ArgumentParser(
        description="Publish an image to the camera topic."
    )
    parser.add_argument("image_path", help="Path to the image file to publish")
    parser.add_argument(
        "--fps", type=int, default=30, help="Frames per second to publish"
    )
    parsed_args, ros_args = parser.parse_known_args()

    rclpy.init(args=ros_args)
    node = ImagePublisherNode(parsed_args.image_path, parsed_args.fps)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
