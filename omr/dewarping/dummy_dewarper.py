from omr.stafflines.staffline import Staffs, StaffLine
import numpy as np
import json
import cv2
import matplotlib.pyplot as plt
import logging
from PIL import Image

logger = logging.Logger("dummy_dewarper")


def shape_to_rect(shape):
    assert(len(shape) == 2)
    return 0, 0, shape[0], shape[1]


def quad_as_rect(quad):
    if quad[0] != quad[2]: return False
    if quad[1] != quad[7]: return False
    if quad[4] != quad[6]: return False
    if quad[3] != quad[5]: return False
    return True


def quad_to_rect(quad):
    assert(len(quad) == 8)
    assert(quad_as_rect(quad))
    return quad[0], quad[1], quad[4], quad[3]


def rect_to_quad(rect):
    assert(len(rect) == 4)
    return rect[0], rect[1], rect[0], rect[3], rect[2], rect[3], rect[2], rect[1]


def griddify(rect, w_div, h_div):
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    x_step = w / w_div
    y_step = h / h_div
    y = rect[1]
    grid_vertex_matrix = []
    for _ in range(h_div + 1):
        grid_vertex_matrix.append([])
        x = rect[0]
        for _ in range(w_div + 1 ):
            grid_vertex_matrix[-1].append([int(x), int(y)])
            x += x_step
        y += y_step

    return np.array(grid_vertex_matrix)


def transform(point, staffs: Staffs):
    x, y = point[0], point[1]
    top_staff_line_d = 10000000
    top_staff_line: StaffLine = None
    bot_staff_line_d = 10000000
    bot_staff_line: StaffLine = None
    for staff in staffs.staffs:
        for staff_line in staff.staff_lines:
            o_y = staff_line.interpolate_y(x)
            if o_y < y and y - o_y < top_staff_line_d:
                top_staff_line = staff_line
                top_staff_line_d = y - o_y

            if o_y > y and o_y - y < bot_staff_line_d:
                bot_staff_line = staff_line
                bot_staff_line_d = o_y - y

    if top_staff_line_d > 1000000:
        top_staff_line_d = bot_staff_line_d
        top_staff_line = bot_staff_line
    elif bot_staff_line_d > 1000000:
        bot_staff_line_d = top_staff_line_d
        bot_staff_line = top_staff_line


    top_offset = top_staff_line.center_y() - top_staff_line.interpolate_y(x)
    bot_offset = bot_staff_line.center_y() - bot_staff_line.interpolate_y(x)

    interp_y = np.interp(y, [top_staff_line.interpolate_y(x), bot_staff_line.interpolate_y(x)], [top_offset, bot_offset])

    return x, np.rint(y - interp_y)


def transform_grid(dst_grid, staffs, shape):
    src_grid = dst_grid.copy()

    for idx in np.ndindex(src_grid.shape[:2]):
        p = src_grid[idx]
        if shape[0] - 1 > p[0] > 0 and shape[1] - 1 > p[1] > 0:
            out = transform(p, staffs)
            src_grid[idx][1] = out[1]

    return src_grid


def grid_to_mesh(src_grid, dst_grid):
    assert(src_grid.shape == dst_grid.shape)
    mesh = []
    for i in range(src_grid.shape[0] - 1):
        for j in range(src_grid.shape[1] - 1):
            src_quad = [src_grid[i    , j    , 0], src_grid[i    , j    , 1],
                        src_grid[i + 1, j    , 0], src_grid[i + 1, j    , 1],
                        src_grid[i + 1, j + 1, 0], src_grid[i + 1, j + 1, 1],
                        src_grid[i    , j + 1, 0], src_grid[i    , j + 1, 1]]
            dst_quad = [dst_grid[i    , j    , 0], dst_grid[i    , j    , 1],
                        dst_grid[i + 1, j    , 0], dst_grid[i + 1, j    , 1],
                        dst_grid[i + 1, j + 1, 0], dst_grid[i + 1, j + 1, 1],
                        dst_grid[i    , j + 1, 0], dst_grid[i    , j + 1, 1]]
            dst_rect = quad_to_rect(dst_quad)
            mesh.append([dst_rect, src_quad])
    return mesh


def dewarp(images, staffs):
    logger.info("Dewarping {} images based on {} staffs".format(len(images), len(staffs.staffs)))
    shape = images[0].size
    dst_grid = griddify(shape_to_rect(shape), 20, 100)
    logger.debug("Transforming grid)")
    src_grid = transform_grid(dst_grid, staffs, shape)
    logger.debug("Creating mesh")
    mesh = grid_to_mesh(src_grid, dst_grid)
    logger.debug("Transforming images based on mesh")
    images = [im.transform(im.size, Image.MESH, mesh) for im in images]
    logger.info("Finished")
    return images


if __name__ == '__main__':
    from gregorian_annotator_server.settings import PRIVATE_MEDIA_ROOT
    import os
    binary = Image.open(os.path.join(PRIVATE_MEDIA_ROOT, 'demo', 'page00000002', 'deskewed_binary.png'))
    gray = Image.open(os.path.join(PRIVATE_MEDIA_ROOT, 'demo', 'page00000002', 'deskewed_gray.jpg'))
    staffs_json = json.load(open(os.path.join(PRIVATE_MEDIA_ROOT, 'demo', 'page00000002', 'annotation.json'), 'r'))
    staffs = Staffs.from_json(staffs_json)
    overlay = np.array(gray)
    staffs.draw(overlay)
    images = [binary, gray, Image.fromarray(overlay)]
    f, ax = plt.subplots(2, len(images), True, True)
    for a, l in enumerate(images):
        ax[0, a].imshow(l)

    images = dewarp(images, staffs)
    for a, l in enumerate(images):
        ax[1, a].imshow(l)

    plt.show()