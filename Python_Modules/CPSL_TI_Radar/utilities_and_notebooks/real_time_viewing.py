import cv2
import numpy as np

# create a black and white numpy array
data = np.zeros((256, 256), dtype=np.uint8)

# create a window to display the video
cv2.namedWindow("Video")

while True:
    # update the data with new values
    data = np.random.randint(0, 256, (256, 256), dtype=np.uint8)

    # display the data as video
    cv2.imshow("Video", data)

    # wait for a key press to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# release the window and exit
cv2.destroyAllWindows()
