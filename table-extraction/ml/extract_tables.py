import argparse
import os
import pickle
import sys

import numpy as np
from ml.TableExtractML import TableExtractorML
from sklearn import linear_model, preprocessing, metrics
from utils.bbox_utils import doOverlap, compute_iou, isContained


def get_bboxes_from_line(line):
    if line == "NO_TABLES":
        return {}
    bboxes = {}
    for bbox in line.split(";"):
        page_num, page_width, page_height, y0, x0, y1, x1 = bbox[1:-1].split(",")
        try:
            bboxes[int(page_num)] += [
                (float(page_width), float(page_height), float(y0), float(x0), float(y1), float(x1))]
        except KeyError:
            bboxes[int(page_num)] = [
                (float(page_width), float(page_height), float(y0), float(x0), float(y1), float(x1))]
    return bboxes


def get_features_and_labels(pdf_list, gt_list):
    pdf_files = [pdf_file.rstrip() for pdf_file in open(pdf_list).readlines()]
    gt = [gt.rstrip() for gt in open(gt_list).readlines()]
    tables = []
    for i, pdf_file in enumerate(pdf_files):
        if i % 10 == 0:
            print "{} documents processed out of {}".format(i, len(pdf_files))
        gt_tables = get_bboxes_from_line(gt[i])
        extractor = TableExtractorML(os.environ['DATAPATH'] + pdf_file)
        bboxes, features = extractor.get_candidates_and_features()
        labels = extractor.get_labels(gt_tables)
        bboxes = [[i] + list(bbox) for bbox in bboxes]
        if i == 0:
            X = np.array(features)
            y = np.array(labels)
            tables = np.array(bboxes)
        else:
            X = np.concatenate((X, np.array(features)), axis=0)
            y = np.concatenate((y, labels), axis=0)
            tables = np.concatenate((tables, bboxes), axis=0)
    X = preprocessing.scale(X, axis=0)
    print "Features computed!"
    return X, y, tables


def load_train_data(pdf_list, gt_list):
    if os.path.exists(pdf_list + '.features.pkl'):
        print "Loading precomputed features for {}..".format(pdf_list)
        # load pickled data
        X = pickle.load(open(pdf_list + '.features.pkl', 'rb'))
        y = pickle.load(open(pdf_list + '.labels.pkl', 'rb'))
        tables = pickle.load(open(pdf_list + '.candidates.pkl', 'rb'))
        print "Features loaded!"
    else:
        print "Building feature matrix for {}".format(pdf_list)
        # compute and pickle feature matrix
        X, y, tables = get_features_and_labels(pdf_list, gt_list)
        pickle.dump(X, open(pdf_list + '.features.pkl', 'wb'))
        pickle.dump(y, open(pdf_list + '.labels.pkl', 'wb'))
        pickle.dump(tables, open(pdf_list + '.candidates.pkl', 'wb'))
    return X, y, tables.astype(np.int)


def get_features(pdf_list):
    pdf_files = [pdf_file.rstrip() for pdf_file in open(pdf_list).readlines()]
    tables = []
    for i, pdf_file in enumerate(pdf_files):
        if i % 10 == 0:
            print "{} documents processed out of {}".format(i, len(pdf_files))
        extractor = TableExtractorML(os.environ['DATAPATH'] + pdf_file)
        bboxes, features = extractor.get_candidates_and_features()
        bboxes = [[i] + list(bbox) for bbox in bboxes]
        if i == 0:
            X = np.array(features)
            tables = np.array(bboxes)
        else:
            X = np.concatenate((X, np.array(features)), axis=0)
            tables = np.concatenate((tables, bboxes), axis=0)
    X = preprocessing.scale(X, axis=0)
    print "Features computed!"
    return X, tables


def load_test_data(pdf_list):
    if os.path.exists(pdf_list + '.features.pkl'):
        print "Loading precomputed features for {}..".format(pdf_list)
        # load pickled data
        X = pickle.load(open(pdf_list + '.features.pkl', 'rb'))
        tables = pickle.load(open(pdf_list + '.candidates.pkl', 'rb'))
        print "Features loaded!"
    else:
        print "Building feature matrix for {}".format(pdf_list)
        # compute and pickle feature matrix
        X, tables = get_features(pdf_list)
        pickle.dump(X, open(pdf_list + '.features.pkl', 'wb'))
        pickle.dump(tables, open(pdf_list + '.candidates.pkl', 'wb'))
    return X, tables.astype(np.int)


def compute_overlap_matrix(pdf_bboxes, iou_thresh):
    nb_tables = len(pdf_bboxes)
    overlap = np.zeros((nb_tables, nb_tables))
    for i, bb1 in enumerate(pdf_bboxes):
        for j, bb2 in enumerate(pdf_bboxes):
            if i != j and bb1[0] == bb2[0] and doOverlap(bb1[-4:], bb2[-4:]):
                iou = compute_iou(bb1[-4:], bb2[-4:])
                if iou > iou_thresh or isContained(bb1[-4:], bb2[-4:]) or isContained(bb2[-4:], bb1[-4:]):
                    overlap[i, j] = 1.
    return overlap


def filter_overlapping_bboxes(overlap_bboxes):
    areas = []
    for bbox in overlap_bboxes:
        top, left, bottom, right = bbox[-4:]
        areas.append((bottom - top) * (right - left))
    bbox = overlap_bboxes[np.argmax(areas)]
    return bbox


def remove_duplicates(pdf_bboxes, iou_thresh):
    filtered_bboxes = []
    overlap = compute_overlap_matrix(pdf_bboxes, iou_thresh)
    bboxes_idx = np.arange(len(pdf_bboxes))
    for i in bboxes_idx:
        if i == -1:
            # ignore this bbox
            pass
        elif np.sum(overlap[i]) == 0:
            #  add this bbox since it does not overlap with any other bboxes
            filtered_bboxes.append(tuple(pdf_bboxes[i]))
        else:
            # we take the bbox with maximum area among overlapping bounding boxes
            overlap_idx = np.concatenate(([i], np.flatnonzero(overlap[i])))
            overlap_bboxes = pdf_bboxes[overlap_idx]
            bbox = filter_overlapping_bboxes(overlap_bboxes)
            filtered_bboxes.append(tuple(bbox))
            bboxes_idx[overlap_idx] = -1
    return filtered_bboxes


def compute_stats(y_pred, y_test):
    recall = metrics.recall_score(y_test, y_pred)
    precision = metrics.precision_score(y_test, y_pred)
    accuracy = metrics.accuracy_score(y_test, y_pred)
    print "Classification Metrics:"
    print "(Note that these statistics are not for the table detection task but for the classification problem."
    print "To run evaluation for the table detection class, refer to the script char_level_evaluation.py)"
    print "Precision: ", precision
    print "Recall: ", recall
    print "F1-score: ", 2 * precision * recall / (precision + recall)
    print "Accuracy:", accuracy


def train_model(X_train, y_train, model_path):
    print "Training model..."
    logistic = linear_model.LogisticRegression()
    logistic.fit(X_train, y_train)
    print "Model trained!"
    pickle.dump(logistic, open(model_path, 'wb'))
    print "Model saved!"
    return logistic


def load_model(model_path):
    print "Loading pretrained model..."
    model = pickle.load(open(model_path, 'rb'))
    print "Model loaded!"
    return model


def filter_bboxes(tables, iou_thresh):
    pdf_idx_to_filtered_bboxes = {}
    pdf_idx = tables[0][0]
    bboxes = []
    for table in tables:
        if table[0] == pdf_idx:
            bboxes.append(tuple(table[1:]))
        else:
            filtered_bboxes = remove_duplicates(np.array(bboxes), iou_thresh)
            pdf_idx_to_filtered_bboxes[pdf_idx] = filtered_bboxes
            pdf_idx = table[0]
            bboxes = [tuple(table[1:])]
    return pdf_idx_to_filtered_bboxes

def bbox_to_dict(tables):
    bbox_dict = {}
    for table in tables:
        try:
            bbox_dict[table[0]] += [tuple(table[1:])]
        except KeyError:
            bbox_dict[table[0]] = [tuple(table[1:])]
    return bbox_dict

def write_bbox_to_file(bbox_file, pdf_idx_to_filtered_bboxes, num_test):
    for i in range(num_test):
        try:
            filtered_bboxes = pdf_idx_to_filtered_bboxes[i]
            bbox_file.write(";".join([str(bbox) for bbox in filtered_bboxes]) + "\n")
        except KeyError:
            bbox_file.write("NO_TABLES\n")
    bbox_file.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
            description="""Script to extract tables bounding boxes from PDF files using a machine learning approach.
            if model.pkl is saved in the model-path, the pickled model will be used for prediction. Otherwise the model will be retrained.
            If --mode is test (by default), the script will create a .bbox file containing the tables for the pdf documents listed in the file --test-pdf.
            If --mode is dev, the script will also extract ground truth labels fot the test data and compute some statistics.
            To run the script on new documents, specify the path to the list of pdf to analyze using the argument --test-pdf. Those files must be saved in the DATAPATH folder.""")
    parser.add_argument('--mode', type=str, default='test', help='usage mode dev or test, default is test')
    parser.add_argument('--train-pdf', type=str, default=os.environ['MLPATH'] + 'train.pdf.list.paleo.not.scanned',
                        help='list of pdf file names used for training. Those files must be saved in the DATAPATH folder (cf set_env.sh)')
    parser.add_argument('--test-pdf', type=str, default=os.environ['MLPATH'] + 'test.pdf.list.paleo.not.scanned',
                        help='list of pdf file names used for testing. Those files must be saved in the DATAPATH folder (cf set_env.sh)')
    parser.add_argument('--gt-train', type=str, default=os.environ['MLPATH'] + 'gt.train',
                        help='ground truth train tables')
    parser.add_argument('--gt-test', type=str, default=os.environ['MLPATH'] + 'gt.test',
                        help='ground truth test tables')
    parser.add_argument('--model-path', type=str, default=os.environ['MLPATH'] + 'model.pkl', help='pretrained model')
    parser.add_argument('--iou-thresh', type=float, default=0.8,
                        help='intersection over union threshold to remove duplicate tables')
    args = parser.parse_args()
    # load or train the model
    if os.path.exists(args.model_path):
        model = load_model(args.model_path)
    else:
        X_train, y_train, tables_train = load_train_data(args.train_pdf, args.gt_train)
        model = train_model(X_train, y_train, args.model_path)
    num_test = len(open(args.test_pdf).readlines())
    if args.mode == 'dev':
        # load dev data (with ground truth, for evaluation)
        X_test, y_test, tables_test = load_train_data(args.test_pdf, args.gt_test)
        # predict tables for dev tables and evaluate
        y_pred = model.predict(X_test)
        print "Testing for {} pdf documents".format(num_test)
        compute_stats(y_pred, y_test)
    elif args.mode == 'test':
        # load test data (with no ground truth)
        X_test, tables_test = load_test_data(args.test_pdf)
        y_pred = model.predict(X_test)
    else:
        print "Mode not recognized, pick dev or test."
        sys.exit()
    predicted_tables = tables_test[np.flatnonzero(y_pred)]
    # todo: remove duplicate tables
    # pdf_idx_to_filtered_bboxes = filter_bboxes(predicted_tables, args.iou_thresh)
    pdf_idx_to_filtered_bboxes = bbox_to_dict(predicted_tables)
    # write tables to file
    bbox_file = open(args.test_pdf + '.bbox', 'w')
    write_bbox_to_file(bbox_file, pdf_idx_to_filtered_bboxes, num_test)
