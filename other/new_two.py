import os
import cv2
import copy
import shutil
import datetime
import numpy as np
import random as rd
import operator as op
import functools as ft
import itertools as it
import collections as col

from skan import csr
from os import listdir
from skimage import morphology
from os.path import isfile, join
from decimal import Decimal, getcontext

from concurrent import futures
from sklearn.cluster import KMeans
from concurrent.futures import ProcessPoolExecutor

# GREEDY APPROACH, 1 MERGE OF TWO LINKS -> RE-CREATE GRAPH, CALCULATE V-SCORES AGAIN THEN MERGE AGAIN
# UNTIL ALL LINKS ARE MERGED, THEN MOVE TO CONFLICT
# THEN STOP --- NEEDS WORK
# ---------------------------------------------------------------------------------
#
def get_nearby_pixels_two_edges(v, w1, w2, edges_dictionary, max_dist):
    v_x, v_y = v
    max_dist_v = [x for x in range(-max_dist, max_dist + 1)]
    max_dist_candidates_x = list(map(lambda x: x + v_x, max_dist_v))
    max_dist_candidates_y = list(map(lambda y: y + v_y, max_dist_v))

    left_column = list(map(lambda e: (v_x - max_dist, e), max_dist_candidates_y))
    right_column = list(map(lambda e: (v_x + max_dist, e), max_dist_candidates_y))
    top_column = list(map(lambda e: (e, v_y - max_dist), max_dist_candidates_x))
    bottom_column = list(map(lambda e: (e, v_y + max_dist), max_dist_candidates_x))

    junction_pixels = dict()
    if tuple([v, w1]) in edges_dictionary.keys():
        junction_pixels[tuple([v, w1])] = edges_dictionary[tuple([v, w1])]
    else:
        junction_pixels[tuple([v, w1])] = edges_dictionary[tuple([w1, v])]

    if tuple([v, w2]) in edges_dictionary.keys():
        junction_pixels[tuple([v, w2])] = edges_dictionary[tuple([v, w2])]
    else:
        junction_pixels[tuple([v, w2])] = edges_dictionary[tuple([w2, v])]

    w1_in_radius = [i for i in left_column + right_column + top_column + bottom_column
                    if i in junction_pixels[(v, w1)]]
    if len(w1_in_radius) == 0:
        w1_in_radius = [w1]

    w2_in_radius = [i for i in left_column + right_column + top_column + bottom_column
                    if i in junction_pixels[(v, w2)]]
    if len(w2_in_radius) == 0:
        w2_in_radius = [w2]

    return w1_in_radius[0], w2_in_radius[0]


# ---------------------------------------------------------------------------------
# get_nearby_pixels
def get_nearby_pixels(u, v, w1, w2, edges_dictionary, max_dist):
    v_x, v_y = v
    max_dist_v = [x for x in range(-max_dist, max_dist + 1)]
    max_dist_candidates_x = list(map(lambda x: x + v_x, max_dist_v))
    max_dist_candidates_y = list(map(lambda y: y + v_y, max_dist_v))

    left_column = list(map(lambda e: (v_x - max_dist, e), max_dist_candidates_y))
    right_column = list(map(lambda e: (v_x + max_dist, e), max_dist_candidates_y))
    top_column = list(map(lambda e: (e, v_y - max_dist), max_dist_candidates_x))
    bottom_column = list(map(lambda e: (e, v_y + max_dist), max_dist_candidates_x))

    junction_pixels = dict()
    if tuple([u, v]) in edges_dictionary.keys():
        junction_pixels[tuple([u, v])] = edges_dictionary[tuple([u, v])]
    else:
        junction_pixels[tuple([u, v])] = edges_dictionary[tuple([v, u])]

    if tuple([v, w1]) in edges_dictionary.keys():
        junction_pixels[tuple([v, w1])] = edges_dictionary[tuple([v, w1])]
    else:
        junction_pixels[tuple([v, w1])] = edges_dictionary[tuple([w1, v])]

    if tuple([v, w2]) in edges_dictionary.keys():
        junction_pixels[tuple([v, w2])] = edges_dictionary[tuple([v, w2])]
    else:
        junction_pixels[tuple([v, w2])] = edges_dictionary[tuple([w2, v])]

    w1_in_radius = [i for i in left_column + right_column + top_column + bottom_column
                    if i in junction_pixels[(v, w1)]]
    if len(w1_in_radius) == 0:
        w1_in_radius = [w1]

    w2_in_radius = [i for i in left_column + right_column + top_column + bottom_column
                    if i in junction_pixels[(v, w2)]]
    if len(w2_in_radius) == 0:
        w2_in_radius = [w2]

    u_in_radius = [i for i in left_column + right_column + top_column + bottom_column
                   if i in junction_pixels[(u, v)]]
    if len(u_in_radius) == 0:
        u_in_radius = [u]

    return u_in_radius[0], w1_in_radius[0], w2_in_radius[0]


# ---------------------------------------------------------------------------------
# calculates angle between three points, result in radians
# using Decimal for increased precision
def calculate_abs_angle(u, v, w):
    # angle between u, v and v, w
    getcontext().prec = 28

    u_x, u_y = u
    v_x, v_y = v
    w_x, w_y = w

    x1 = (u_x - v_x).item()
    y1 = (u_y - v_y).item()
    x2 = (w_x - v_x).item()
    y2 = (w_y - v_y).item()

    dot = Decimal(x1 * x2 + y1 * y2)
    norma_1 = Decimal(x1 * x1 + y1 * y1).sqrt()
    norma_2 = Decimal(x2 * x2 + y2 * y2).sqrt()

    val = dot / (norma_1 * norma_2)

    return np.abs(np.arccos(float(val)))


# ---------------------------------------------------------------------------------
# finds "best" out of local region angle and complete edge angle - for each edge
# totals 6 possible combinations
#
def calculate_edge_scores(u, v, edge_dictionary, t_scores, excluded, max_dist):
    junction_v_edges = [edge for edge in edge_dictionary
                        if (edge[0] == v and edge[1] != u) or (edge[0] != u and edge[1] == v)]
    v_edges = [e[0] if e[1] == v else e[1] for e in junction_v_edges]

    # For each edge we check u,v v,w1 v,w2
    for combination in it.combinations(v_edges, 2):
        w1, w2 = combination
        if w1 in excluded or w2 in excluded:
            continue
        # get coordinates in radius max_dist - then calculate angle
        in_u, in_w1, in_w2 = get_nearby_pixels(u, v, w1, w2, edge_dictionary, max_dist=max_dist)
        u_s = [u, in_u]
        w1_s = [w1, in_w1]
        w2_s = [w2, in_w2]
        uv_vw1 = [calculate_abs_angle(one_u, v, one_w1) for one_u in u_s for one_w1 in w1_s]
        uv_vw2 = [calculate_abs_angle(one_u, v, one_w2) for one_u in u_s for one_w2 in w2_s]
        w1v_vw2 = [calculate_abs_angle(one_w1, v, one_w2) for one_w1 in w1_s for one_w2 in w2_s]
        uv_bridge = np.min([np.abs(np.pi - one_w1v_vw2) + np.abs(np.pi / 2.0 - one_uv_vw1) +
                            np.abs(np.pi / 2.0 - one_uv_vw2) for one_w1v_vw2 in w1v_vw2
                            for one_uv_vw1 in uv_vw1 for one_uv_vw2 in uv_vw2])
        vw1_bridge = np.min([np.abs(np.pi - one_uv_vw1) + np.abs(np.pi / 2.0 - one_uv_vw2) +
                             np.abs(np.pi / 2.0 - one_w1v_vw2) for one_uv_vw1 in uv_vw1
                             for one_uv_vw2 in uv_vw2 for one_w1v_vw2 in w1v_vw2])
        vw2_bridge = np.min([np.abs(np.pi - one_uv_vw2) + np.abs(np.pi / 2.0 - one_uv_vw1) +
                             np.abs(np.pi / 2.0 - one_w1v_vw2) for one_uv_vw2 in uv_vw2
                             for one_uv_vw1 in uv_vw1 for one_w1v_vw2 in w1v_vw2])
        t_scores[(u, v, w1, w2)] = [(u, v, uv_bridge), (v, w1, vw1_bridge), (v, w2, vw2_bridge)]


# ---------------------------------------------------------------------------------
#
def create_v_scores(t_scores, l_scores):
    def normalise(max_val, min_val, val):
        return (val - min_val) / (max_val - min_val)

    # normalise t_scores [0, 1]
    all_scores = [x[2] for value in t_scores.values() for x in value]
    max_t = np.max(all_scores)
    min_t = np.min(all_scores)

    l_values = list(l_scores.values())
    max_l = np.max(l_values)
    min_l = np.min(l_values)

    # normalise l_scores [0, 1]
    # we add v l_score to the correct places in t_scores dictionary
    v_scores = dict()
    for t_score in t_scores.keys():
        v = t_score[1]
        l_score = l_scores[v]
        scores = t_scores[t_score]
        v_score = list(map(lambda x: (x[0], x[1], normalise(max_t, min_t, x[2]) +
                                      normalise(max_l, min_l, l_score)), scores))
        v_scores[t_score] = v_score

    return v_scores


# ---------------------------------------------------------------------------------
# calculate_junctions_t_scores
def calculate_junctions_t_scores(edge_dictionary, excluded):
    time_print('calculating t scores ...')
    t_scores = dict()
    for edge in edge_dictionary:
        # new t_scores added to t_scores variable inside calculate_edge_scores
        u, v = edge
        # print(u)
        # print(v)
        # print(excluded)
        if u in excluded or v in excluded:
            continue
        calculate_edge_scores(u, v, edge_dictionary, t_scores, excluded, max_dist=7)
        calculate_edge_scores(v, u, edge_dictionary, t_scores, excluded, max_dist=7)
    # return all possibilities
    return t_scores


# ---------------------------------------------------------------------------------
# calculate minimum l_score for each vertex
def calculate_junctions_l_scores(edge_dictionary, vertexes, excluded, max_dist=7):
    time_print('calculating l scores ...')
    vertexes_l_scores = dict()
    for vertex in vertexes:
        if vertex in excluded:
            # print('vertex=', vertex)
            continue
        # print('v=', vertex)
        # get list of edges that that vertex is part of
        edges_of_vertex = [e for e in edge_dictionary.keys() if e[0] == vertex or e[1] == vertex]
        # print('edges_of_v=', edges_of_vertex)
        junction_l_scores = dict()
        junctions = []
        l_scores = []
        for combination in it.combinations(edges_of_vertex, 2):
            e1, e2 = combination
            e1_e1, e1_e2 = e1
            e2_e1, e2_e2 = e2
            if e1_e1 in excluded or e1_e2 in excluded or e2_e1 in excluded or e2_e2 in excluded:
                # print ('e1_e1=', e1_e1, 'e1_e2=', e2_e2, 'e2_e1=', e2_e1, 'e2_e2=', e2_e2)
                continue
            # print('e1=', e1, 'e2=', e2)
            w1 = e1[0] if e1[0] != vertex else e1[1]
            w2 = e2[0] if e2[0] != vertex else e2[1]
            # print('w1=', w1, 'w2=', w2)

            # get coordinates in radius 9 - then calculate angle
            in_w1, in_w2 = get_nearby_pixels_two_edges(vertex, w1, w2, edge_dictionary, max_dist=max_dist)

            angle_w1v_vw2 = calculate_abs_angle(in_w1, vertex, in_w2)

            edges_of_w1 = [e for e in edge_dictionary.keys() if e[0] == w1 and e[1] != vertex
                           or e[1] == w1 and e[0] != vertex]
            edges_of_w2 = [e for e in edge_dictionary.keys() if e[0] == w2 and e[1] != vertex
                           or e[1] == w2 and e[0] != vertex]
            # print('edges_of_w1=', edges_of_w1)
            # print('edges_of_w2=', edges_of_w2)
            for edge_of_w1 in edges_of_w1:
                w1_e1, w1_e2 = edge_of_w1
                if w1_e1 in excluded or w1_e2 in excluded:
                    # print('w1_e1=', w1_e1, 'w1_e2=', w1_e2)
                    continue
                z1 = edge_of_w1[0] if edge_of_w1[0] != w1 else edge_of_w1[1]
                in_v, in_z1 = get_nearby_pixels_two_edges(w1, vertex, z1, edge_dictionary, max_dist=max_dist)
                # print('z1=', z1)
                angle_z1w1_w1v = calculate_abs_angle(in_z1, w1, in_v)
                for edge_of_w2 in edges_of_w2:
                    w2_e1, w2_e2 = edge_of_w2
                    if w2_e1 in excluded or w2_e2 in excluded:
                        # print('w2_e1=', w2_e1, 'w2_e2=', w2_e2)
                        continue
                    z2 = edge_of_w2[0] if edge_of_w2[0] != w2 else edge_of_w2[1]
                    in_v, in_z2 = get_nearby_pixels_two_edges(w2, vertex, z2, edge_dictionary, max_dist=max_dist)
                    # print('z2=', z2)
                    angle_z2w2_w2v = calculate_abs_angle(in_z2, w2, in_v)
                    junctions.append((z1, w1, vertex, w2, z2))

                    l_scores.append(np.abs(np.pi - angle_w1v_vw2) * 0.5 +
                                    np.abs(np.pi - angle_z1w1_w1v) * 0.25 +
                                    np.abs(np.pi - angle_z2w2_w2v) * 0.25)
                    junction_l_scores[(z1, w1, vertex, w2, z2)] = np.abs(np.pi - angle_w1v_vw2) * 0.5 + \
                                                                  np.abs(np.pi - angle_z1w1_w1v) * 0.25 + \
                                                                  np.abs(np.pi - angle_z2w2_w2v) * 0.25
        # print(junction_l_scores)
        # min_junction = junctions[np.argmin(l_scores)]
        # print('min junction=', min_junction, 'min score=', min_score)
        if l_scores:  # TODO why would this happen
            min_score = np.min(l_scores)
            vertexes_l_scores[vertex] = min_score
    # print(vertexes_l_scores)
    return vertexes_l_scores


# ---------------------------------------------------------------------------------
# document pre processing
def pre_process(path, file_name):
    def cluster_elements(all_stats):
        n_clusters = 9
        data_list = [stat[5] for stat in all_stats]
        # print('data_list=', data_list)
        data = np.asarray(data_list).reshape(-1, 1)
        k_means = KMeans(n_clusters=n_clusters)
        k_means.fit(data)
        y_k_means = k_means.predict(data)

        cluster_size = [len(list(filter(lambda x: x == i, y_k_means))) for i in range(n_clusters)]
        # print('cluster_size=', cluster_size)
        # print('y_k_means=', list(y_k_means))
        cluster_total = [ft.reduce(lambda x, y: x + y[1] if y[0] == i else x, zip(list(y_k_means), data_list), 0)
                         for i in range(n_clusters)]
        minimum_cluster = np.argmin([x[1]/x[0] for x in zip(cluster_size, cluster_total)])
        # print('cluster_total=', cluster_total)
        # print('min_cluster=', minimum_cluster)
        # exit()
        return y_k_means, minimum_cluster

    # load image as gray-scale,

    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    cv2.imwrite('./' + file_name + '/original_image.png', image)
    cv2.imwrite('./' + file_name + '/original_image.png_inverted', 255 - image)
    # image = cv2.erode(image, np.ones((3, 3), np.uint8), iterations=3)
    # cv2.imwrite('./' + file_name + '/dilated_image.png', image)
    # using gaussian adaptive thresholding
    image = cv2.adaptiveThreshold(image, 1, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 255, 9)
    cv2.imwrite('./' + file_name + '/gaus.png', image * 255)
    cv2.imwrite('./' + file_name + '/gaus_inverted.png', 255 - image * 255)
    # convert to binary using otsu binarization
    # image = cv2.threshold(image, 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    # remove small connected components - aim for smallest 10% and in an increasing step until 2x size
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(image, connectivity=8, ltype=cv2.CV_32S)
    stats = np.asarray([np.append(stat[0], stat[1]) for stat in zip(range(num_labels), stats)])

    results, min_cluster = cluster_elements(stats)
    index = 0
    time_print('elements to be deleted: ' + str(np.count_nonzero(results == 0)))
    for clustered in results:
        if clustered == min_cluster:
            # print('deleted:', index, 'size=', stats[index, 5])
            labels[labels == index] = 0
        index += 1

    labels[labels != 0] = 1
    # cv2.namedWindow('image')
    # cv2.imshow('image', image * 255)
    image_no_tiny_elements = op.and_(image, labels.astype(np.uint8))
    # invert colors
    # image_no_tiny_elements = 1 - image_no_tiny_elements
    # image = 1 - image

    # cv2.namedWindow('res')
    # cv2.imshow('res', res * 255)
    # cv2.waitKey()
    # cv2.destroyAllWindows()

    # print('components_to_delete=', components_to_delete)
    # print('num_labels=', num_labels)
    # print('labels=', labels)
    # print('stats=', stats)
    # print('centroids=', centroids)

    # add white border around image of size 29
    white_border_added_image = cv2.copyMakeBorder(image, 29, 29, 29, 29, cv2.BORDER_CONSTANT, None, 0)
    white_border_added_image_no_tiny_elements = cv2.copyMakeBorder(image_no_tiny_elements, 29, 29, 29, 29,
                                                                   cv2.BORDER_CONSTANT, None, 0)
    # on top of that add black border of size 1
    black_border_added = cv2.copyMakeBorder(white_border_added_image, 1, 1, 1, 1, cv2.BORDER_CONSTANT, None, 1)
    black_border_added_no_tiny_elements = cv2.copyMakeBorder(white_border_added_image_no_tiny_elements,
                                                             1, 1, 1, 1, cv2.BORDER_CONSTANT, None, 1)
    # invert images (now black is black and white is white)
    black_border_added = 1 - black_border_added
    black_border_added_no_tiny_elements = 1 - black_border_added_no_tiny_elements

    cv2.imwrite('./' + file_name + '/preprocessed_image.png', black_border_added * 255)
    cv2.imwrite('./' + file_name + '/preprocessed_image_inverted.png', 255 - black_border_added * 255)

    cv2.imwrite('./' + file_name + '/preprocessed_image_no_tiny_elements.png', black_border_added_no_tiny_elements * 255)
    cv2.imwrite('./' + file_name + '/preprocessed_image_no_tiny_elements_inverted.png',
                255 - black_border_added_no_tiny_elements * 255)

    return black_border_added, black_border_added_no_tiny_elements


# ---------------------------------------------------------------------------------
# returns for edge (u,v) its shortest connected list of pixels from pixel u to pixel v
def edge_bfs(start, end, skeleton):

    visited = set()
    to_visit = col.deque([start])
    edges = col.deque()
    done = False
    while not done and to_visit:
        current = to_visit.popleft()
        visited.add(current)
        candidates = [v for v in connected_candidates(current, skeleton)
                      if v not in visited and v not in to_visit]
        # print('candidates=', candidates)
        for vertex in candidates:
            edges.append([current, vertex])
            to_visit.append(vertex)
            if vertex == end:
                done = True
    # print('start=', start, 'end=', end)
    # print('candidates=', edges)
    # exit()

    # find path from end -> start
    final_edges = [end]
    current = end
    failed = False
    while current != start and not failed:
        # print('current=', current)
        sub_edges = list(filter(lambda item: item[1] == current, edges))
        # print('sub_edges=', sub_edges)
        if sub_edges:
            one_edge = sub_edges.pop()
            final_edges.append(one_edge[0])
            current = one_edge[0]
        else:
            failed = True

    final_edges.append(start)
    # print('finalEdges=', final_edges)
    # exit()

    if failed:
        print(start, end, 'fail')
        return start, end, []
    else:
        # print(start, end, 'success')
        return start, end, final_edges


# ---------------------------------------------------------------------------------
# retrieves connected pixels that are part of the edge pixels
# to be used for the bfs algorithm
# 8 connected neighborhood of a pixel
def connected_candidates(pixel, skeleton):
    def add_offset(offset):
        return tuple(map(op.add, pixel, offset))

    def in_bounds_and_true(p):
        r, c = add_offset(p)
        if 0 <= r < skeleton.shape[0] and 0 <= c < skeleton.shape[1] and skeleton[r][c]:
            return True
        else:
            return False

    eight_connected = list(filter(in_bounds_and_true, [(1, 0), (0, 1), (-1, 0), (0, -1),
                                                                      (1, 1), (-1, 1), (-1, -1), (1, -1)]))

    return [add_offset(offset) for offset in eight_connected]


# ---------------------------------------------------------------------------------
# All vertexes with one degree (take part of one edge only) - they are removed
# All vertexes with two degree (take part of two edges exactly) - they are merged
# if three edges create a three edged circle: (u,v) (v,w) (w,u), we remove (w,u)
# this is done iteratively, until all vertexes have a degree of three or more!
def prune_graph(skeleton, iter_index, file_name, prune_circle=True):
    def in_bounds(p):
        r, c = p
        if 0 <= r < skeleton.shape[1] and 0 <= c < skeleton.shape[0]:
            return True
        else:
            return False

    def add_range(tup):
        v_x, v_y = tup
        max_dist_v = [x for x in range(-7, 7 + 1)]
        max_dist_candidates_x = list(map(lambda x: x + v_x, max_dist_v))
        max_dist_candidates_y = list(map(lambda y: y + v_y, max_dist_v))
        return [(x, y) for x in max_dist_candidates_x for y in max_dist_candidates_y if in_bounds((x, y))]

    def unique_rows(a):
        a = np.ascontiguousarray(a)
        unique_a = np.unique(a.view([('', a.dtype)] * a.shape[1]))
        return unique_a.view(a.dtype).reshape((unique_a.shape[0], a.shape[1]))

    def identical(e1, e2):
        return e1[0] == e2[0] and e1[1] == e2[1]

    cv2.imwrite('./' + file_name + '/skel_' + str(iter_index) + '.png', skeleton.astype(np.uint8) * 255)
    cv2.imwrite('./' + file_name + '/skel_' + str(iter_index) + '_inverted.png', 255 - skeleton.astype(np.uint8) * 255)
    # important! removes pixels due to vertex removal from previous iteration
    skeleton = morphology.skeletonize(skeleton)

    branch_data = csr.summarise(skeleton)
    coords_cols = (['img-coord-0-%i' % i for i in [1, 0]] +
                   ['img-coord-1-%i' % i for i in [1, 0]])
    # removes duplicate entries! for some reason they are present in the result
    coords = unique_rows(branch_data[coords_cols].values).reshape((-1, 2, 2))
    try_again = False

    len_before = len(coords)
    excludes = [(0, 0), (skeleton.shape[1], 0), (0, skeleton.shape[0]), (skeleton.shape[1], skeleton.shape[0])]
    exclude = []
    excluded = []
    for ex in excludes:
        exclude.extend(add_range(ex))

    done = False
    while not done:
        changed = False
        flat_coords = [tuple(val) for sublist in coords for val in sublist]
        unique_flat_coords = list(set(flat_coords))
        current = 0
        while not changed and current < len(unique_flat_coords):
            item = unique_flat_coords[current]
            current += 1
            # print('item=', item, 'count=', flat_coords.count(item))
            # 1 degree vertexes are to be removed from graph
            if flat_coords.count(item) < 2:
                # print('item=', item)
                if item in exclude:
                    excluded.append((item[1], item[0]))
                    continue
                changed = True
                coords = list(filter(lambda x: tuple(x[0]) != item and tuple(x[1]) != item, coords))
                # print('flat_coords.count(item)=', flat_coords.count(item), 'fc=', fc)
            # 2 degree vertexes need their edges to be merged
            elif flat_coords.count(item) == 2:
                changed = True
                fc = list(filter(lambda x: tuple(x[0]) == item or tuple(x[1]) == item, coords))
                # print('flat_coords.count(item)=', flat_coords.count(item), 'fc=', fc)
                if len(fc) != 2:
                    print('item=', item, 'fc=', fc)
                coords = list(filter(lambda x: tuple(x[0]) != item and tuple(x[1]) != item, coords))
                e1_s = fc[0][0]
                e1_e = fc[0][1]
                e2_s = fc[1][0]
                e2_e = fc[1][1]
                if ft.reduce(op.and_, map(lambda e: e[0] == e[1], zip(e1_s, e2_s))) and \
                        not identical(e1_e, e2_e):
                    coords.append(np.array([e1_e, e2_e]))
                elif ft.reduce(op.and_, map(lambda e: e[0] == e[1], zip(e1_s, e2_e))) and \
                        not identical(e1_e, e2_s):
                    coords.append(np.array([e1_e, e2_s]))
                elif ft.reduce(op.and_, map(lambda e: e[0] == e[1], zip(e1_e, e2_s))) and \
                        not identical(e1_s, e2_e):
                    coords.append(np.array([e1_s, e2_e]))
                elif ft.reduce(op.and_, map(lambda e: e[0] == e[1], zip(e1_e, e2_e))) and \
                        not identical(e1_s, e2_s):
                    coords.append(np.array([e1_s, e2_s]))
                else:
                    changed = False
        if not changed:
            done = True
            time_print('before= ' + str(len_before) + ' after= ' + str(len(coords)))
            try_again = len_before != len(coords)

    tmp_skel = copy.deepcopy(skeleton)
    for coord in coords:
        start, end = coord
        start = (start[1], start[0])
        end = (end[1], end[0])
        # print(start, end)
        start_neighborhood = connected_candidates(start, skeleton)
        end_neighborhood = connected_candidates(end, skeleton)
        for point in start_neighborhood + end_neighborhood:
            tmp_skel[point] = False
        tmp_skel[start] = False
        tmp_skel[end] = False

    results = []
    results_dict = dict()
    for edge in coords:
        start, end = edge
        start = (start[1], start[0])
        end = (end[1], end[0])
        start_neighborhood = connected_candidates(start, skeleton)
        end_neighborhood = connected_candidates(end, skeleton)
        for point in start_neighborhood + end_neighborhood:
            tmp_skel[point] = True
        tmp_skel[start] = True
        tmp_skel[end] = True
        _, _, result = edge_bfs(start, end, tmp_skel)
        start_neighborhood = connected_candidates(start, skeleton)
        end_neighborhood = connected_candidates(end, skeleton)
        for point in start_neighborhood + end_neighborhood:
             tmp_skel[point] = False
        tmp_skel[start] = False
        tmp_skel[end] = False
        results.append((start, end, result))
        results_dict[(start, end)] = result

    # filter out circles -> (u,v) (v,w) (w,u), then (w,u) is removed
    # (w,u) is the longest line out of the three in a 3-edge circle
    remove_candidates = set()
    for result in results_dict.keys():
        v, u = result
        candidates_v = [e for e in results_dict.keys() if v in e and u not in e]
        candidates_v_w = [e[0] if e[1] == v else e[1] for e in candidates_v]
        candidates_u = [e for e in results_dict.keys() if u in e and v not in e]
        candidates_u_w = [e[0] if e[1] == u else e[1] for e in candidates_u]
        for vw in candidates_v_w:
            for uw in candidates_u_w:
                if vw == uw:
                    w = vw
                    if (v, u) in results_dict.keys():
                        candidate_vu = (v, u)
                        len_vu = len(results_dict[(v, u)])
                    else:
                        candidate_vu = (u, v)
                        len_vu = len(results_dict[(u, v)])

                    if (w, v) in results_dict.keys():
                        candidate_wv = (w, v)
                        len_wv = len(results_dict[(w, v)])
                    else:
                        candidate_wv = (v, w)
                        len_wv = len(results_dict[(v, w)])

                    if (u, w) in results_dict.keys():
                        candidate_uw = (u, w)
                        len_uw = len(results_dict[(u, w)])
                    else:
                        candidate_uw = (w, u)
                        len_uw = len(results_dict[(w, u)])
                    if len_vu > len_uw and len_vu > len_wv:
                        remove_candidates.add(candidate_vu)
                    elif len_uw > len_vu and len_uw > len_wv:
                        remove_candidates.add(candidate_uw)
                    elif len_wv > len_vu and len_wv > len_vu:
                        remove_candidates.add(candidate_wv)
    # remove all edges that create a 3-edged circle,
    # for each edge the removed edge is the longest of all 3-edges of the circle
    time_print('removing circles ...')
    remove_items = [(edge[0], edge[1], results_dict.pop(edge)) for edge in remove_candidates]
    # if no edge was removed above, but a circle is removed, we need a new iteration due to changes.
    if remove_items:
        try_again = True
    time_print('before= ' + str(len(results)) + ' to_remove= ' + str(len(remove_items)))
    results = list(filter(lambda element: element not in remove_items, results))

    # create new skeleton following graph pruning
    skel = np.zeros_like(skeleton)
    for result in results:
        u, v, pixel_list = result
        for point in pixel_list:
            skel[point] = True

    return skel, results, excluded, try_again


# ---------------------------------------------------------------------------------
# time print - add time to printout
def time_print(msg):
    print('[' + str(datetime.datetime.now()) + ']', msg)


# ---------------------------------------------------------------------------------
# extract local maxima pixels
def calculate_local_maxima_mask(image):
    def uint8_array(rows):
        return np.array(rows).astype(np.uint8)

    base = list(map(uint8_array, [
        [
            [0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
        ],
        [
            [0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0,  1, 0],
        ],
        [
            [0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0],
        ],
    ]))

    kernels = [mat for mat in base + [mat.T for mat in base]]

    local_maxima_result = (image > cv2.dilate(image, kernel)
                           for kernel in kernels)

    return ft.reduce(op.or_, local_maxima_result).astype(np.uint8)


# ---------------------------------------------------------------------------------
# ridge extraction
def ridge_extraction(image_preprocessed):
    # apply distance transform then normalize image for viewing
    dist_transform = cv2.distanceTransform(image_preprocessed, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)

    # normalize distance transform to be of values [0,1]
    normalized_dist_transform = cv2.normalize(dist_transform, None, 0, 1.0, cv2.NORM_MINMAX)

    # extract local maxima pixels -- "ridge pixels"
    dist_maxima_mask = calculate_local_maxima_mask(normalized_dist_transform)
    # retrieve the biggest connected component only
    dist_maxima_mask_biggest_component = np.zeros_like(dist_maxima_mask)

    for val in np.unique(dist_maxima_mask)[1:]:
        mask = np.uint8(dist_maxima_mask == val)
        labels, stats = cv2.connectedComponentsWithStats(mask, 4)[1:3]
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        dist_maxima_mask_biggest_component[labels == largest_label] = val

    # we extract our own skeleton, here we just use thinning after ridge extraction
    skeleton = morphology.skeletonize(dist_maxima_mask_biggest_component)

    return skeleton


# ----------
#
def make_graph(skeleton, file_name):
    time_print('pruning redundant edges and circles...')
    excluded = []
    results = []
    changed = True
    iter_index = 0
    while changed:
        time_print('iter ' + str(iter_index))
        skeleton, results, excluded, changed = prune_graph(skeleton, iter_index, file_name)
        iter_index += 1
    time_print('done')
    time_print('making initial graph...')

    edge_dictionary = dict()
    for result in results:
        start, end, edge_list = result
        if start == end:  # TODO WHY THE GRAPH HAS THESE EDGES? BUG IN LIBRARY?
            continue
        edge_dictionary[(start, end)] = edge_list

    # get vertexes
    graph_vertexes = list(set([tuple(val) for sublist in edge_dictionary.keys() for val in sublist]))

    return skeleton, edge_dictionary, graph_vertexes, excluded,


# ---------------------------------------------------------------------------------
#
def greedy_classification(t_scores, edge_dictionary):
    # in greedy manner: find junction in v_scores where u,v v,w1 v,w2 has minimum T score
    # mark u,v as Bridge
    # mark v,w1 and v,w2 as Link
    # TODO OPTION 1 - 100% greedy - and remove conflicts on the go
    # remove all u,v from v_scores marked as L
    # remove all v,w1 and v,w2 from v_scores marked as B
    # TODO OPTION 2 - each time check for conflicts, and mark as such
    # add junction to B and L lists
    # check whether new min junction
    bridges = set()
    links = set()
    time_print('greedy manner labeling ...')

    index = 1
    time_print('start=' + str(len(t_scores)))
    while t_scores:
        if index % 500 == 0:
            time_print(len(t_scores))
        # else:
        #     print(len(t_scores), end=' ')
        index += 1
        # find minimum score for each junction
        min_t_scores = dict()
        for key in t_scores.keys():
            min_score_index = np.argmin(map(lambda e_1, e_2, score: score, t_scores[key]))
            min_t_scores[key] = t_scores[key][min_score_index]

        # print(min_t_scores.values())
        # find junction with minimum score of all junctions
        values = [value[2] for value in min_t_scores.values()]
        min_score_index = np.argmin(values)
        min_score_key = list(min_t_scores.keys())[min_score_index]
        min_score = min_t_scores[min_score_key]
        # print('min_score_index=', min_score_index, 'min_score_key=', min_score_key, 'min_score=', min_score)
        # add to bridges - CHECK FOR CONFLICT
        new_bridge = (min_score[0], min_score[1])
        if new_bridge not in edge_dictionary.keys():
            p1, p2 = new_bridge
            new_bridge = (p2, p1)

        # print('t_scores[min_score_key]=', t_scores[min_score_key])
        # add to links - CHECK FOR CONFLICT
        two_links = [item for item in t_scores[min_score_key] if item is not min_score]
        # print('two_links=', two_links)
        # add new links to links set

        if new_bridge not in links:
            bridges.add(new_bridge)
            for link in two_links:
                e1, e2, _ = link
                new_link = (e1, e2)
                if new_link not in edge_dictionary.keys():
                    new_link = (e2, e1)
                links.add(new_link)
        # check for conflicts before adding them??
        # add new bridge to bridges set
        # remove minimum t score junction from t_scores
        t_scores.pop(min_score_key)
        # print('B=', bridges, 'L=', links)
    print()

    # find anchor edges
    anchors = [x for x in edge_dictionary.keys() if x not in set(bridges).union(links)]

    # mark edges connected to anchor points as conflict edges
    for bridge in bridges:
        for coord in [coord for edge in anchors for coord in edge]:
            if coord in bridge:
                links.add(bridge)
                break

    return bridges, links, anchors, edge_dictionary


# ---------------------------------------------------------------------------------
# auxiliary function to overlay edges on original image
def overlay_edges(image, edge_list, color=None):
    image_copy = copy.deepcopy(image)

    # random_color = (100, 156, 88)
    if color is None:
        random_color = (rd.randint(50, 255), rd.randint(50, 255), rd.randint(50, 255))
    else:
        random_color = color
    for point in edge_list:
        # print('point=', point)
        # cv2.circle(image, point, radius, random_color, cv2.FILLED)
        r, g, b = image_copy[point]
        if r == 0 and g == 0 and b == 0:
            image_copy[point] = random_color
        else:
            image_copy[point] = (0, 255, 255)
    return image_copy


# ---------------------------------------------------------------------------------
# draw_edges(edges, edge_dictionary, image, color):
def draw_edges(edges, edge_dictionary, image, color):
    for edge in edges:
        edge_list = edge_dictionary[edge]
        image = overlay_edges(image, edge_list, color)
    return image


# ---------------------------------------------------------------------------------
# get humanly distinguishable colors
def get_spaced_colors(n):
    max_value = 255**3
    min_value = 150**3
    interval = int(max_value / n)
    colors = [hex(I)[2:].zfill(6) for I in range(min_value, max_value, interval)]
    return [(int(i[:2], 16), int(i[2:4], 16), int(i[4:], 16)) for i in colors]


# ---------------------------------------------------------------------------------
# draw_graph_edges
def draw_graph_edges(edge_dictionary, ridges_mask, window_name, wait_flag=False, overlay=False):
    if overlay:
        after_ridge_mask = ridges_mask
    else:
        after_ridge_mask = cv2.cvtColor(np.zeros_like(ridges_mask), cv2.COLOR_GRAY2RGB)

    random_colors = get_spaced_colors(len(edge_dictionary.values()) * 2)
    i = 0
    for edge_list in edge_dictionary.values():
        after_ridge_mask = overlay_edges(after_ridge_mask, edge_list, random_colors[i])
        i += 1
    for two_vertex in edge_dictionary.keys():
        v1, v2 = two_vertex
        after_ridge_mask[v1] = (255, 255, 255)
        after_ridge_mask[v2] = (255, 255, 255)

    time_print('SAVED: ./' + window_name + '/final_result.png')
    cv2.imwrite('./' + window_name + '/final_result.png', after_ridge_mask)
    cv2.imwrite('./' + window_name + '/final_result_inverted.png', 255 - after_ridge_mask)
    if wait_flag:
        cv2.namedWindow(window_name)
        cv2.imshow(window_name, after_ridge_mask)
        cv2.waitKey()
        cv2.destroyAllWindows()

    return after_ridge_mask


# ---------------------------------------------------------------------------------
#
def overlay_and_save(bridges, links, rest, edge_dictionary, image_preprocessed, file_name, score_type):
    image = 1 - image_preprocessed
    image *= 255
    image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    image = draw_edges(bridges, edge_dictionary, image, (255, 0, 0))
    image = draw_edges(links, edge_dictionary, image, (0, 255, 0))
    # rest = [x for x in edge_dictionary.keys() if x not in set(bridges).union(links)]
    image = draw_edges(rest, edge_dictionary, image, (0, 0, 255))
    cv2.imwrite('./' + file_name + '/overlayed_classifications_' + score_type + '.png', image)

    return image


# -
#
def merge_once(candidate_links, edge_dict, anchors):
    # we combine two links as one if angle between them is minimum
    changed = False
    merge_link_1 = []
    merge_link_2 = []
    merge_angles = 0
    for link in candidate_links:
        u, v = link
        # print('link=', link)
        neighbors = [l for l in candidate_links if v in l and u not in l]
        # print('neighbors=', neighbors)
        if neighbors:
            angles = [calculate_abs_angle(u, v, e[0] if e[1] == v else e[1]) for e in neighbors]
            # print('angles=', angles)
            max_index = np.argmax(angles)
            max_neighbor = neighbors[max_index]
            if angles[max_index] > merge_angles:
                merge_angles = angles[max_index]
                merge_link_1 = link
                merge_link_2 = max_neighbor

        # if we reached anchor points we do not merge them. we stop.
        found = False
        for coord in [coord for edge in anchors for coord in edge]:
            if coord in merge_link_1 and coord in merge_link_2:
                found = True

        # now we merge 'best' candidates together modifying the document graph
        if not found and merge_link_1:
            # print('link_1=', merge_link_1, 'link_2=', merge_link_2, 'angle=', merge_angles)
            changed = True
            pixels_1 = edge_dict.pop(merge_link_1)
            pixels_2 = edge_dict.pop(merge_link_2)
            candidate_links = [e for e in candidate_links if e != merge_link_1 and e != merge_link_2]
            # find shared vertex
            if merge_link_1[0] == merge_link_2[0]:
                shared_vertex = merge_link_1[0]
            else:
                shared_vertex = merge_link_1[1]
            # find all edges that have that vertex as part of it
            flat_anchors = list(set([coord for edge in anchors for coord in edge]))
            all_edges = [e for e in edge_dict.keys() if shared_vertex in e and e[1]]
            # not in flat_anchors and e[1] not in flat_anchors

            # print('all_edges=', all_edges)
            # remove them
            for e in all_edges:
                edge_dict.pop(e)

            # make new edge and its pixels
            new_edge = (merge_link_1[0], merge_link_2[0] if merge_link_2[0] != merge_link_1[1] else merge_link_2[1])
            # new_pixels = list(set([*pixels_1, *pixels_2]))
            new_pixels = list(set(pixels_1 + pixels_2))
            edge_dict[new_edge] = new_pixels
            candidate_links.append(new_edge)
            time_print('=> ' + str(merge_link_1) + ' + ' + str(merge_link_2) + ' = ' + str(new_edge))
            break

    return candidate_links, edge_dict, changed


# ---------------------------------------------------------------------------------
#
def combine_two_edges(bridges, links, rest, edge_dictionary):
    # draw_graph_edges(edge_dictionary, res, 'before', wait_flag=False, overlay=True)

    can_be_both = [e for e in links if e in bridges]
    # bridges = [e for e in bridges if e not in can_be_both]
    definite_links = [e for e in links if e not in bridges]

    # remove bridges from graph that are not marked as conflict
    only_bridges = [bridge for bridge in bridges if bridge not in can_be_both]
    for bridge in only_bridges:
        edge_dictionary.pop(bridge)

    # combine edges - first iteration for link edges
    definite_links, edge_dictionary, try_again = merge_once(definite_links, edge_dictionary, rest)
    if not try_again:
        time_print('CONFLICT NOW!!')
        both = definite_links + can_be_both
        # combine edges - second iteration, now we include conflict edges
        both, edge_dictionary, try_again = merge_once(both, edge_dictionary, rest)

    return edge_dictionary, try_again


# ---------------------------------------------------------------------------------
# main execution function
def execute(input_path):
    # retrieve list of images
    images = [f for f in listdir(input_path) if isfile(join(input_path, f))]
    i = 1

    for image in images:
        file_name = image.split('.')[0]
        print('[' + str(i) + '/' + str(len(images)) + ']', file_name)
        file_name = 'results/' + file_name
        if os.path.exists(file_name) and os.path.isdir(file_name):
            shutil.rmtree(file_name)
        os.mkdir(file_name)

        # pre-process image
        time_print('pre-process image...')
        image_view, image_preprocessed = pre_process(input_path + image, file_name)
        # create dir for results

        # extract ridges
        time_print('extract ridges, junctions...')
        try_again = True
        combined_graph = []
        image = copy.deepcopy(image_preprocessed)
        time_print('extract ridges, junctions...')
        skeleton = ridge_extraction(image)
        while try_again:
            skeleton, edge_dictionary, vertexes, excluded = make_graph(skeleton, file_name)
            cv2.namedWindow('skeleton')
            cv2.imshow('skeleton', skeleton.astype(np.uint8) * 255)

            t_scores = calculate_junctions_t_scores(edge_dictionary, excluded)
            l_scores = calculate_junctions_l_scores(edge_dictionary, vertexes, excluded)
            v_scores = create_v_scores(t_scores, l_scores)
            bridges, links, rest, edge_dictionary = greedy_classification(v_scores, edge_dictionary)

            image = cv2.cvtColor(np.zeros_like(skeleton, np.uint8), cv2.COLOR_GRAY2RGB)
            image = draw_edges(bridges, edge_dictionary, image, (255, 0, 0))
            image = draw_edges(links, edge_dictionary, image, (0, 255, 0))
            image = draw_edges(rest, edge_dictionary, image, (0, 0, 255))
            cv2.namedWindow('image')
            cv2.imshow('image', image)

            combined_graph, try_again = combine_two_edges(bridges, links, rest, edge_dictionary)
            skeleton = np.zeros_like(skeleton)
            for edge in combined_graph.values():
                for point in edge:
                    skeleton[point] = True
            cv2.namedWindow('res')
            cv2.imshow('res', skeleton.astype(np.uint8) * 255)
            cv2.waitKey()
            cv2.destroyAllWindows()

        image = 1 - image_view
        image *= 255
        res = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        draw_graph_edges(combined_graph, res, file_name, wait_flag=False, overlay=True)
        i += 1


if __name__ == "__main__":
        # execute_parallel("./data/original/")
        # execute_parallel("./data/")
        execute("./data/")


#
def combine_two_edge_vertexes(combined_graph):
    print('finding vertexes with degree 2 ...')
    done = False
    while not done:
        all_vertexes = [coord for edge in combined_graph.keys() for coord in edge]
        vertexes = list(set(all_vertexes))
        done = True
        for vertex in vertexes:
            two_links = [link for link in combined_graph.keys() if vertex in link]
            if len(two_links) == 2:
                pixels_1 = combined_graph.pop(two_links[0])
                pixels_2 = combined_graph.pop(two_links[1])
                new_edge = (two_links[0][0], two_links[1][0] if two_links[1][0] != two_links[0][1] else two_links[1][1])
                combined_graph[new_edge] = pixels_1 + pixels_2
                done = False
                break
    return combined_graph
