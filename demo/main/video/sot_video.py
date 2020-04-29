# -*- coding: utf-8 -*
from paths import ROOT_PATH  # isort:skip
from videoanalyst.config.config import cfg
from videoanalyst.config.config import specify_task
from videoanalyst.model import builder as model_builder
from videoanalyst.pipeline import builder as pipeline_builder
from videoanalyst.utils import complete_path_wt_root_in_cfg, load_image
from videoanalyst.pipeline.utils.bbox import xywh2xyxy, xyxy2xywh
from videoanalyst.utils.image import ImageFileVideoStream, ImageFileVideoWriter

import os.path as osp
import glob
import argparse
from loguru import logger

import cv2
import numpy as np
import time
import torch

font_size = 0.5
font_width = 1


def make_parser():
    parser = argparse.ArgumentParser(
        description="press s to select the target box,\n \
                        then press enter or space to confirm it or press c to cancel it,\n \
                        press c to stop track and press q to exit program")
    parser.add_argument(
        "-cfg",
        "--config",
        default="experiments/siamfcpp/test/got10k/siamfcpp_alexnet-got.yaml",
        type=str,
        help='experiment configuration')
    parser.add_argument("-d",
                        "--device",
                        default="cpu",
                        type=str,
                        help="torch.device, cuda or cpu")
    parser.add_argument("-v",
                        "--video",
                        type=str,
                        default="webcam",
                        help="path to input video file, default is webcam")
    parser.add_argument("-o",
                        "--output",
                        type=str,
                        default="",
                        help="path to dump the track video")
    parser.add_argument("-s",
                        "--start-index",
                        type=int,
                        default=0,
                        help="start index / #frames to skip")
    return parser


def main(args):
    root_cfg = cfg
    root_cfg.merge_from_file(args.config)
    logger.info("Load experiment configuration at: %s" % args.config)

    # resolve config
    root_cfg = complete_path_wt_root_in_cfg(root_cfg, ROOT_PATH)
    root_cfg = root_cfg.test
    task, task_cfg = specify_task(root_cfg)
    task_cfg.freeze()
    window_name = task_cfg.exp_name
    # build model
    model = model_builder.build(task, task_cfg.model)
    # build pipeline
    pipeline = pipeline_builder.build(task, task_cfg.pipeline, model)
    dev = torch.device(args.device)
    pipeline.set_device(dev)
    init_box = None
    template = None
    vw = None

    # create video stream
    if args.video == "webcam":
        logger.info("[INFO] starting video stream...")
        vs = cv2.VideoCapture(0)
        vs.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
    elif not osp.isfile(args.video):
        vs = ImageFileVideoStream(args.video, init_counter=args.start_index)
    else:
        vs = cv2.VideoCapture(args.video)

    # create video writer to output video
    if args.output:
        if osp.isdir(args.output):
            vw = ImageFileVideoWriter(args.output)
        else:
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            width, height = vs.get(3), vs.get(4)
            vw = cv2.VideoWriter(args.output, fourcc, 25,
                                 (int(width), int(height)))

    # loop over sequence
    while vs.isOpened():
        key = 255
        ret, frame = vs.read()
        logger.debug("frame: {}".format(ret))
        if ret:
            if init_box is not None:
                time_a = time.time()
                rect_pred = pipeline.update(frame)
                logger.debug(rect_pred)
                show_frame = frame.copy()
                time_cost = time.time() - time_a
                bbox_pred = xywh2xyxy(rect_pred)
                bbox_pred = tuple(map(int, bbox_pred))
                cv2.putText(show_frame,
                            "track cost: {:.4f} s".format(time_cost), (128, 20),
                            cv2.FONT_HERSHEY_COMPLEX, font_size, (0, 0, 255),
                            font_width)
                cv2.rectangle(show_frame, bbox_pred[:2], bbox_pred[2:],
                              (0, 255, 0))
                if template is not None:
                    show_frame[:128, :128] = template
            else:
                show_frame = frame
            cv2.imshow(window_name, show_frame)
            if vw is not None:
                vw.write(show_frame)
        # catch key if
        if (init_box is None) or (vw is None):
            logger.debug("Press key s to select object.")
            key = cv2.waitKey(30) & 0xFF
        logger.debug("key: {}".format(key))
        if key == ord("q"):
            break
        # if the 's' key is selected, we are going to "select" a bounding
        # box to track
        elif key == ord("s"):
            # select the bounding box of the object we want to track (make
            # sure you press ENTER or SPACE after selecting the ROI)
            logger.debug("Select object to track")
            box = cv2.selectROI(window_name,
                                frame,
                                fromCenter=False,
                                showCrosshair=True)
            if box[2] > 0 and box[3] > 0:
                init_box = box
                template = cv2.resize(
                    frame[box[1]:box[1] + box[3], box[0]:box[0] + box[2]],
                    (128, 128))
                pipeline.init(frame, init_box)
                logger.debug(
                    "pipeline initialized with bbox : {}".format(init_box))
        elif key == ord("c"):
            logger.debug(
                "init_box/template released, press key s to select object.")
            init_box = None
            template = None
    vs.release()
    if vw is not None:
        vw.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = make_parser()
    args = parser.parse_args()
    main(args)
