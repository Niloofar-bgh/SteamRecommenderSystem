from pyspark.sql import SparkSession
import pyspark.mllib.linalg.distributed  as LAD


path = "C:\\Users\\hamid\\PycharmProjects\\bigdata-game-recommender\\data\\steam_data_sample.csv"
#path = "C:\\Users\\hamid\\PycharmProjects\\bigdata-game-recommender\\data\\data_test2.csv"
########################## Loading Data ###########################
spark = SparkSession \
        .builder \
        .appName("Python Spark SQL basic example") \
        .config("spark.some.config.option", "some-value") \
        .getOrCreate()

def abs(a):
    if (a < 0):
        return a * -1
    else:
        return a

def get_data(file_name):
    rdd = spark.read.csv(file_name, header =True).rdd
    rdd = rdd.map(lambda l: (int(l['Game ID']), (int(l['User ID']),float(l['Hours Played']))))\
        .filter(lambda l: l[1][1] < 5000)

    #print(rdd.take(10))
    return rdd

def normalize_data(rdd):
    mean_rdd = rdd.map(lambda l: (0,(l[1][1], 1)))\
        .reduceByKey(lambda x,y:(x[0]+y[0], x[1]+y[1]))\
        .map(lambda l: l[1][0]/l[1][1]).collect()
    #print(mean_rdd)
    mean_rdd = mean_rdd[0]
    def normalize(x,m):
        s = (x - m) ** 2
        if (s == 0):
            return 0
        return (x - m) /s
    rdd_norm = rdd.mapValues(lambda l: (l[0], normalize(l[1], mean_rdd)))
    #print(rdd_norm.take(15))
    return rdd_norm

def normalize_data_by_game(rdd):
    #calculate mean per game
    mean_rdd = rdd.mapValues(lambda l: (l[1], 1))\
        .reduceByKey(lambda x,y: (x[0]+y[0], x[1]+y[1]))\
        .mapValues(lambda l: l[0]/l[1])
    #print(mean_rdd.take(10))
    rdd_meanInc = rdd.join(mean_rdd)
    rdd_meanInc.cache()
    #print(rdd_meanInc.take(10))

    #calculate stdev per game
    stdev_rdd = rdd_meanInc.mapValues(lambda l: (((l[0][1]-l[1]) ** 2), 1))\
        .reduceByKey(lambda x,y: (x[0]+y[0], x[1]+y[1]))\
        .mapValues(lambda l: (l[0]/(l[1])) ** 1/2) #l[1]-1
    #print(stdev_rdd.take(10))
    rdd_mean_std = rdd_meanInc.join(stdev_rdd)
    #print(rdd_mean_std.take(10))
    def normalize(x,m,s):
        if (s == 0):
            return 0
        return (x - m) /s

    rdd_norm = rdd_mean_std.mapValues(lambda l: (l[0][0][0], normalize(l[0][0][1],l[0][1],l[1])))
    #print(rdd_norm.take(10))
    return rdd_norm

def get_training_test(rdd):
    (training, test) = rdd.randomSplit([0.8, 0.2], 123)
    return training, test

def get_game_user_matrix(rdd, all_users):
    rdd = rdd.groupByKey().mapValues(list)
    #print(rdd.take(5))

    def get_user_vector(l):
        res = []
        dic_l = dict(l)
        for u in all_users:
            if u in dic_l:
                res.append( dic_l[u]) #(u, dic_l[u]))
            else:
                res.append(0) #(u, 0))
        return res

    rdd = rdd.mapValues(lambda l: get_user_vector(l))
    #print(rdd.take(5))
    return rdd

def get_similarity_matrix(game_user_matrix):
    #Note:result is based on coordinate instead of game_ID
    iu_matrix = LAD.IndexedRowMatrix(game_user_matrix)
    iu_matrix = iu_matrix.toBlockMatrix().transpose().toIndexedRowMatrix()
    sim_matrix = iu_matrix.columnSimilarities()
    sim = sim_matrix.entries.map(lambda l: ((l.i, l.j), l.value) )
    return sim
    #sim_matrix = sim_matrix.toBlockMatrix()
    #sim = sim_matrix.toLocalMatrix().toArray()
    #tran_sim = sim_matrix.transpose().toLocalMatrix().toArray()
    #print(tran_sim)


def get_recommended_user_vector(game_user_mat,game,similar_game):
    game_user = game_user_mat.filter(lambda l: l[0] == game).take(1)
    sim_game_user = game_user_mat.filter(lambda l: l[0] == similar_game).take(1)

    def sync_games(origin_gu,source_gu):
        rec_user_vector = []
        i = 0
        for r in origin_gu:
            if(r <= 0 and source_gu[i] > 0):
                rec_user_vector.append(source_gu[i])
            else:
                rec_user_vector.append(r)
        return rec_user_vector

    rec = sync_games(game_user[0][1], sim_game_user[0][1])
    #print(rec)
    return rec

data = get_data(path)
data.cache()

# two different way of normalization
data_norm = normalize_data(data)
#data_norm = normalize_data_by_game(data)

data.cache()

print(data_norm.take(30))
training, test = get_training_test(data_norm)
training.cache()
test.cache()
#print(training.take(10))
users = training.map(lambda l: l[1][0]).distinct().collect()
users = sorted(users)
#print(users)
game_user_mat = get_game_user_matrix(training,users)
#print(game_user_mat.take(10))
game_user_mat.cache()
games = game_user_mat.keys().collect()
#print(games)

index_game_user = game_user_mat.zipWithIndex()
index_game_user = index_game_user.map(lambda l: (l[1],l[0][1]))
#print(index_game_user.take(10))

sim_mat = get_similarity_matrix(index_game_user).collect()
sim_mat = dict(sim_mat)
#print(sim_mat)

game_user_mat = game_user_mat.collect()
game_user = dict(game_user_mat)
#print(game_user)

def get_similar_games( game):
    # m is number of similar games that should be concidered
    sim_games = []
    if (game in games):
        g_index = games.index(game)
        res1 = [((k1,_), v) for (k1, _), v in sim_mat.items() if k1 == g_index]
        res2 = [((_,k2), v) for (_, k2), v in sim_mat.items() if k2 == g_index]
        sims = res1 + res2
        sims = dict(sims)
        #print("game:")
        #print(game)
        #print(g_index)
        def get_game_from_coordinate(i,j):
            #print("i,j")
            #print(i)
            #print(",")
            #print (j)
            res = -1
            if (i == g_index):
                res = games[j]
            else:
                res = games[i]
            return res

        for key, value in sorted(sims.items(), key=lambda item: item[1], reverse = True):
            if (value > 0):
                game = get_game_from_coordinate(key[0], key[1])
                sim_games.append((game, value))
        #print("sim-games")
        #print(sim_games)
    return sim_games


def get_rec_rate(game, user):
    sim_games = get_similar_games(game)
    if (len(sim_games) == 0):
        return 0

    if (user in users):
        u_index = users.index(user)

        most_sim = sim_games[:5]
        nominator = 0
        dinom = 0
        for sg in most_sim:
            user_vec = game_user.get(sg[0])
            #print(user_vec)
            r = user_vec[u_index]
            nominator += (r * sg[1])
            dinom += sg[1]

        if (dinom == 0):
            return 0
        else:
            return nominator/dinom
    else:
        return 0

rec = test.map(lambda l:(l[0], l[1], get_rec_rate(l[0], l[1][0])))
#print("test_recommended")
#print(rec.take(10))

def get_error_d(r1,r2):
    return round((r1 - r2) ** 2, 5)

error = rec.map(lambda l: (0, (get_error_d(l[1][1] ,l[2]),1)))
error.cache()
#print("error:")
#print(error.take(10))
#total_num = error.count()
#print("total-n")
#print(total_num)
error = error.reduceByKey(lambda x,y: (x[0]+y[0], x[1]+y[1]))
#print(error.take(10))

error = error.collect()
#print(error)
rmse = (error[0][1][0] ** 1/2)/error[0][1][1]
print("rmse:")
print(rmse)
