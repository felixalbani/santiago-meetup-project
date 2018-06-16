from __future__ import print_function
import sys
import os

#if os.path.exists('yolo3.zip'):
#    sys.path.insert(0, 'yolo3.zip')

import traceback
import json
import requests
import io
import logging

from pyspark import SparkContext, SparkConf
from pyspark.streaming import StreamingContext
from pyspark.sql import SparkSession, HiveContext
from pyspark.sql.types import Row
from pyspark.streaming.kafka import KafkaUtils


import twitter
import helper
from yolo import YOLO
from PIL import Image

# Batch interval default 5 seconds
BATCH_INTERVAL = 30

MODEL_DATA_DIR = "model_data"
FONT_DIR = "font"

#logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def map_tweet(record):
    yolo = YOLO(MODEL_DATA_DIR, FONT_DIR)
    try:
        tweet = json.loads(record[1])

        # process tweet
        source_img, result_image, result_meta = twitter.process_tweet(tweet, yolo)

        return (str(tweet["id"]), "twitter", tweet["user"]["screen_name"],
                tweet["text"], helper.to_bytearray(source_img), helper.to_bytearray(result_image), result_meta)
    except:
        print("Unexpected error:", sys.exc_info()[0])
        traceback.print_exc(file=sys.stdout)

    return (None, None, None, None, None, None, None)

def map_scores(record):
    rmeta = record[6]
    key = record[0]
    row = []
    i=0
    for m in rmeta:
        row.append((key+'-'+str(i), key, m[0],m[1],m[2][0],m[2][1],m[3][0],m[3][1]))
        i=i+1
    return row

def save_meetup_to_hbase(result):
    if(not result.isEmpty()):
        schema = ['key', 'source', 'user', 'message',
                  'original_image', 'result_image']
        df = result.toDF(schema)
        # df.printSchema()

        catalog = json.dumps({"table": {"namespace": "default", "name": "meetup"},
                              "rowkey": "key",
                              "columns":
                              {"key": {"cf": "rowkey", "col": "key", "type": "string"},
                               "source": {"cf": "cf", "col": "source", "type": "string"},
                               "user": {"cf": "cf", "col": "user", "type": "string"},
                               "message": {"cf": "cf", "col": "message", "type": "string"},
                               "original_image": {"cf": "cf", "col": "original_image", "type": "binary"},
                               "result_image": {"cf": "cf", "col": "result_image", "type": "binary"}
                               }})
        df.write.option("catalog", catalog).option("newtable", "5").format(
            "org.apache.spark.sql.execution.datasources.hbase").save()

def save_meetup_tags_to_hbase(result):
    if(not result.isEmpty()):
        schema = ['key', 'meetup_key', 'class', 'score', 'x1',
                  'y1', 'x2', 'y2']
        df = result.toDF(schema)
        # df.printSchema()

        catalog = json.dumps({"table": {"namespace": "default", "name": "meetup_tags"},
                              "rowkey": "key",
                              "columns":
                              {"key": {"cf": "rowkey", "col": "key", "type": "string"},
                               "meetup_key": {"cf": "cf", "col": "meetup_key", "type": "string"},
                               "class": {"cf": "cf", "col": "class", "type": "string"},
                               "score": {"cf": "cf", "col": "score", "type": "float"},
                               "x1": {"cf": "cf", "col": "x1", "type": "int"},
                               "y1": {"cf": "cf", "col": "y1", "type": "int"},
                               "x2": {"cf": "cf", "col": "x2", "type": "int"},
                               "y2": {"cf": "cf", "col": "y2", "type": "int"}
                               }})
        df.write.option("catalog", catalog).option("newtable", "5").format(
            "org.apache.spark.sql.execution.datasources.hbase").save()



if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: main.py <broker_list> <topic>", file=sys.stderr)
        exit(-1)

    # read command line arguments
    brokers, topic = sys.argv[1:]

    sparkSession = (SparkSession
                    .builder
                    .appName('Santiago Meetup')
                    .getOrCreate())

    ssc = StreamingContext(sparkSession.sparkContext, BATCH_INTERVAL)

    kvs = KafkaUtils.createDirectStream(ssc, [topic], {"metadata.broker.list": brokers, "auto.offset.reset": "smallest"})
    #kvs = KafkaUtils.createDirectStream(
    #    ssc, [topic], {"metadata.broker.list": brokers, "auto.offset.reset": "largest"})

    result = kvs.map(lambda record: map_tweet(record)).filter(
        lambda record: record[0] is not None).cache()

    scores = result.flatMap(lambda record: map_scores(record)).foreachRDD(lambda rdd: save_meetup_tags_to_hbase(rdd))

    result.map(lambda r: (r[0],r[1],r[2],r[3],r[4],r[5])).foreachRDD(lambda rdd: save_meetup_to_hbase(rdd))

    # create_dir_if_not_exists("result")
    #r_file_name = "result/"+tweet["id_str"]+".PNG"
    # r_image.save(r_file_name,format='PNG')
    # tweet_image(r_file_name,tweet["user"]["screen_name"],tweet["id"])

    #kvs.foreachRDD(lambda rdd: rdd.foreachPartition(process_tweet))

    ssc.start()
    ssc.awaitTermination()
