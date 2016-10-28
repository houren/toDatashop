#!/usr/bin/env python
# import cgi, exceptions, os, pwd, re, time, tempfile, threading
import cgi, exceptions, os, re, time, tempfile, threading, datetime
from subprocess import Popen, PIPE, STDOUT

try:
    from pysqlite2 import dbapi2 as sqlite
except ImportError, ie:
    from sqlite3 import dbapi2 as sqlite

try:
    import uuid
except ImportError, ie:
    import compat.uuid


def uuidgen():
    return unicode(uuid.uuid1())


# ==========================================================
# ===================== DATABASE STUFF =====================
# ==========================================================
def getColmap(conn, name):
    """
  Gets a dictionary of colname (string) to index (0-based integer)
  from the given table when you do a SELECT * ... query.
  You can use it to reference a column by name:
  e.g. result[colmap['id']] gets the value of the 'result' column.
  It also includes a key __NAMES__ which is an array of the column
  names in the same order as they appear in the table.
  """
    res = conn.execute("SELECT * FROM %s LIMIT 1;" % name)
    colmap = dict()
    names = [col[0] for col in res.description]
    for x in xrange(len(names)):
        colmap[names[x]] = x
    colmap['__NAMES__'] = names
    return colmap


def tableExists(conn, name):
    res = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in res]
    return name in tables


def fixupDB(conn, version):
    if not tableExists(conn, 'globals'):
        res = conn.execute("CREATE TABLE globals (version TEXT);")
        res = conn.execute("INSERT INTO globals VALUES ('%s')" % version)
    if not tableExists(conn, 'rtstats'):
        res = conn.execute("""CREATE TABLE rtstats (uid TEXT PRIMARY KEY NOT NULL, per_ans_correct DOUBLE);""")
    if not tableExists(conn, 'history'):
        res = conn.execute("""CREATE TABLE history (uuid TEXT PRIMARY KEY NOT NULL,time DOUBLE,
                          time_out DOUBLE,uid TEXT,gid TEXT,speaker TEXT,goal_name TEXT,
                          goal_index TEXT,step_type TEXT,step_index TEXT,
                          phrase_difficulty TEXT,recipe_difficulty TEXT,
                          sem TEXT,string TEXT,normalized_string TEXT,
                          matched_answer_string TEXT,concepts TEXT,
                          concepts_found TEXT,truth_values TEXT,
                          coverage REAL,obligations TEXT);""")
    if not tableExists(conn, 'kchistory'):
        res = conn.execute("""CREATE TABLE kchistory
                           (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            uuid TEXT,
                            kc TEXT NOT NULL,
                            FOREIGN KEY(uuid) REFERENCES history(uuid));""")

    if not tableExists(conn, 'groups'):
        res = conn.execute("""CREATE TABLE groups (uid TEXT PRIMARY KEY NOT NULL,
                          gid TEXT NOT NULL, atype TEXT NOT NULL);""")
    if not tableExists(conn, 'session'):
        res = conn.execute("""CREATE TABLE session (sid INTEGER PRIMARY KEY AUTOINCREMENT,
                          gid TEXT NOT NULL, start DOUBLE NOT NULL, end DOUBLE);""")
    # Create any columns that may not appear in older databases.
    res = conn.execute("SELECT * FROM history LIMIT 1;")
    cols = [col[0] for col in res.description]
    newish = [['concepts_found', 'TEXT'], ['time_out', 'DOUBLE'], ['kclist', 'TEXT']]
    for col, ctype in newish:
        if col not in cols:
            res = conn.execute("ALTER TABLE history ADD COLUMN %s %s;" % (col, ctype))


def databaseToHTML(conn=None, path=None, uid=None, fields=None, sql=None,
                   formatTime=False, callback=None):
    """Returns an HTML table with the specified database.
  If 'conn' is non-None then it uses an existing SQLite connection.
  Otherwise it creates a connection to the database at 'path'.
  If 'uid' is not None, only gets events for that student.
  If 'sql' is not None, use that instead of the SELECT * from history... stuff.
  If 'formatTime' is True, then the 'time' field will be formatted as a human
  readable string rather than a real number of seconds.
  If 'callback' is passed, it must be a callable taking one string parameter,
  and it will be invoked to (presumably) print the HTML, and this routine
  will not buffer the HTML into one giant string.
  The HTML is encoded in the default site Python encoding (usually ASCII).
  """
    html = ''

    def accumulate(s):
        if callback is not None:
            callback(s)
        else:
            html += s

    if conn is None and path is not None:
        conn = sqlite.connect(path)
    if conn is None:
        raise IOError, "no database path or connection specified"
    systembg = "#8888BB"
    studentbg = "#AAAADD"
    if sql is not None:
        sql = sql.strip()
        if not sql.endswith(';'):
            sql = sql + ';'
    else:
        if uid is None:
            restriction = ''
        else:
            restriction = " WHERE uid='%s'" % uid
        sql = "SELECT * FROM history %s ORDER BY time, step_type DESC;" % restriction
    res = conn.execute(sql)
    colmap = dict()
    cols = [col[0] for col in res.description]
    for x in xrange(len(cols)):
        colmap[cols[x]] = x
    accumulate("<table border='0' cellspacing='1' cellpadding='2' align='center'><tbody>")
    accumulate("<tr bgcolor='#AAAAAA'>")
    for col in cols:
        if fields is None or col in fields:
            accumulate("<td><b>%s</b></td>\n" % col)
    accumulate("</tr>\n")
    if formatTime:
        timeRow = colmap.get('time')
    else:
        timeRow = None
    for row in res:
        speakerRow = colmap.get('speaker')
        if speakerRow is not None and row[speakerRow] == 'system':
            background = systembg
        else:
            background = studentbg
        accumulate("<tr bgcolor='%s'>" % background)
        for i in xrange(len(row)):
            if fields is None or cols[i] in fields:
                item = row[i]
                colorstr = ''
                if item is None:
                    colorstr = ' bgcolor="#333333"'
                    item = ''
                elif type(item) == type(float()):
                    if i == timeRow:
                        item = time.asctime(time.localtime(item))
                    else:
                        item = "%f" % item
                accumulate("<td%s>%s</td>" % (colorstr, item))
        accumulate("</tr>\n")
    accumulate("</tbody></table>\n")
    if callback is not None:
        return html


# dbfields = ('uuid','time','uid','gid','speaker','goal_name','goal_index','step_type',
#            'step_index','phrase_difficulty',='recipe_difficulty','sem','string',
#            'normalized_string','matched_answer_string','concepts','truth_values',
#            'coverage','obligations')

def databaseToDataShop(path, classinfo=None):
    """Returns a dictionary of uid->list of XML documents with the specified database.
  The XML is encoded in UTF-8.
  """
    result = dict()
    session = 1
    scenario = os.path.basename(path)
    scenario = re.search(r'dialogue-history-(.+?)\.db', scenario).group(1)
    conn = sqlite.connect(path)
    curs = conn.cursor()
    res = curs.execute("SELECT DISTINCT (uid) FROM history;")
    uids = [r[0] for r in res]
    xml = ''
    tskill = ''
    sskill = ''
    # Expand the classinfo into <class> XML
    cmclass = ''
    category = ''
    superKCList = dict({"1": "r15", "2": "r13", "3": "r1", "4": "r13", "5": "r1", "6": "r12", "7": "r12", "8": "r13",
                        "9": "r4", "10": "r7", "11": "r15", "12": "r13", "13": "r15", "14": "r13", "15": "r18",
                        "16": "r20", "17": "r20",
                        "18": "r22", "19": "na", "20": "r17", "21": "r22", "22": "r17", "23": "na", "24": "r21",
                        "25": "na", "26": "r17",
                        "27": "r25", "28": "r10", "29": "r14", "30": "r10", "31": "r14", "32": "r11", "33": "r10",
                        "34": "r10", "35": "r11",
                        "36": "r11", "37": "r11", "38": "r2", "39": "r8", "40": "r9", "41": "r27", "42": "na",
                        "43": "na", "44": "na",
                        "45": "na", "46": "r3", "47": "r16", "48": "r28", "49": "r6", "50": "r6", "51": "r6",
                        "52": "r25", "53": "r26",
                        "54": "r29", "55": "r24", "56": "r23", "57": "r5", "58": "r30", "59": "r23", "60": "r18",
                        "61": "r19"})  # stores all super KC mappings kc->superKC

    if classinfo is not None:
        gotOne = False
        cmclass = "\n  <class>\n"
        for key in ['name', 'school', 'period', 'description', 'instructor']:
            if key in classinfo:
                gotOne = True
                cmclass += "    <%s>%s</%s>\n" % (key, classinfo[key], key)
        if gotOne:
            cmclass += "  </class>"
        else:
            cmclass = ''
    cmdataset = """
      <dataset>
        <name>"KCinDyn"</name>
        <level type="Scenario">
          <name>%(scenario)s</name>
          <problem tutorFlag="tutor">
            <name>%(scenario)s</name>
          </problem>
            </level>
            </dataset>
      """ % locals()

    with open('output.xml', 'a') as the_file:
        header = u"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tutor_related_message_sequence SYSTEM "http://learnlab.web.cmu.edu/dtd/tutor_message_v4.dtd">
<tutor_related_message_sequence version_number="4">\n"""
        the_file.write(str(header))

    for uid in uids:
        sessions = list()
        #    header = u"""<?xml version="1.0" encoding="UTF-8"?>

        # <!DOCTYPE tutor_related_message_sequence SYSTEM "http://learnlab.web.cmu.edu/dtd/tutor_message_v4.dtd">

        # <tutor_related_message_sequence version_number="4">\n"""
        # uid = 'summary.cc.10'
        sql = "SELECT * FROM history WHERE uid='%s' ORDER BY time, step_type DESC;" % uid

        # sql = "SELECT * FROM history WHERE uid=%s ORDER BY time, step_type DESC;", ('summary.cc.10',)

        curs = conn.cursor()
        curs_s = conn.cursor()
        res = curs.execute(sql) #original command


        #toexec = curs.execute(sql)
        #res = toexec.fetchall()
        allres = res.fetchall()
        # print(uid)

        # print(len(res.fetchall()))


        colmap = dict()
        oldname = "something"
        cols = [col[0] for col in res.description]
        #cols = [col[0] for col in res.description]
        for x in xrange(0, len(cols)):
            colmap[cols[x]] = x
        # colmap['uuid'] is now '0', the index of that named column
        truth = None
        concepts = None
        messageCount = 0
        firstrow = False
        # print(uid)

        for row in allres:

            if not firstrow:
                cmuuid = uuidgen()
                t = timeDS(row[colmap['time']])
                tz = time.tzname[time.daylight]
                goalname = str(row[colmap['goal_name']])


                seqnum = 0
                firstrow = True


            message = ''
            st = row[colmap['step_type']]
            if st is not None and st.startswith('logout'):
                session += 1
                if messageCount:
                    sessions.append(xml.encode('utf-8'))
                xml = ''
                messageCount = 0
                continue
            ruuid = row[colmap['uuid']]
            rawString = row[colmap['string']]
            stepname = row[colmap['step_type']]
            feedback = row[colmap['coverage']]

            if rawString is not None:
                rawString = cgi.escape(rawString)
            step_index = row[colmap['step_index']]
            if row[colmap['speaker']] == 'system':
                tskill = ''
                ae = ''
                #if row[colmap['truth_values']] is not None:
                #    truth = row[colmap['truth_values']]
                #    ae = "\n\t\t\t<action_evaluation>%s</action_evaluation>" % truthDS(truth)
                #else:
                #    ae = "\n\t\t\t<action_evaluation>UNKNOWN</action_evaluation>"

                # if truth is not None:
                #    ae = "\n\t\t\t<action_evaluation>%s</action_evaluation>" % truthDS(truth)
                #    truth = None
                ta = ''
                if rawString is not None:
                    ta = "\n\t\t\t<tutor_advice><![CDATA[%s]]></tutor_advice>" % rawString
                sem = row[colmap['sem']]
                tkclist = row[colmap['kclist']]

                if tkclist is not None:
                    kc_sql = "SELECT kc from kchistory WHERE uuid='%s';" % row[colmap['uuid']]
                    kc_res = curs.execute(kc_sql)
                    for kc_row in kc_res:
                        # print kc_row[0]
                        stringskill = kc_row[0]
                        #print(stringskill)
                        pskill, category = stringskill.split(".")



                        if ((category == "c") or (category == "p") or (category == "t") or (category == "y")):

                            ae = "\n\t\t\t<action_evaluation>CORRECT</action_evaluation>"
                        elif ((category == "w") or (category == "b")):
                            ae = "\n\t\t\t<action_evaluation>INCORRECT</action_evaluation>"
                        else:
                            ae = "\n\t\t\t<action_evaluation>UNKNOWN</action_evaluation>"




                        #skill = superKCList.keys()[superKCList.values().index(str(('"')+ pskill)+('"'))]
                        skill = superKCList[pskill]


                         # tskill = tskill + "\n\t\t\t<skill><name>%s</name><category>tutor turn</category></skill>" % kc_row[0]
                    tskill = tskill + "\n\t\t\t<skill><name>%s</name><category>tutor turn</category></skill>" % skill

                    # 250716-start editing
                    # if sem is not None and sem != 'na':
                    #    tskill = tskill + "\n\t\t\t<skill><name>%s</name><category>sem</category></skill>" % sem
                    # else:
                    # tskill = tskill + "\n\t\t\t<skill><name>%s</name><category>None</category></skill>" % 'None'
                    # tkclist = row[colmap['kclist']]
                    # if tkclist is not None:
                    # kc_sql = "SELECT kc from kchistory WHERE uuid='%s';" % row[colmap['uuid']]
                    # kc_res = curs.execute(kc_sql)
                    # for kc_row in kc_res:
                    # tskill = tskill + "\n\t\t\t<skill><name>%s</name><category>kc</category></skill>" % kc_row[0]
                    # 250716-stop editing

                # goal_name 	goal_index 	step_type 	step_index
                goal = row[colmap['goal_name']]

                concepts = row[colmap['concepts']]
                # Because we need at least one semantic event
                fullse = ''
                if goal is None:
                    goal = 'na'
                    fullse = goal
                # gse = '\n\t\t\t<semantic_event transaction_id="%s" name="goal_name">%s</semantic_event>' % (ruuid, goal)


                gise = ''
                goalname = row[colmap['goal_name']]
                if (goalname is not None):
                    longname = goalname.split("-")
                    probname = str(longname[0])

                goalindex = row[colmap['goal_index']]
                if goalindex is not None:
                    fullse = fullse + "," + goalindex
                    gise = '\n\t\t\t<semantic_event transaction_id="%s" name="goal_index">%s</semantic_event>' % (
                        ruuid, goalindex)
                stse = ''
                steptype = row[colmap['step_type']]
                if steptype is not None:
                    fullse = fullse + "," + steptype
                    stse = '\n\t\t\t<semantic_event transaction_id="%s" name="step_type">%s</semantic_event>' % (
                        ruuid, steptype)
                sise = ''
                stepindex = row[colmap['step_index']]
                if stepindex is not None:
                    fullse = fullse + "," + stepindex
                    sise = '\n\t\t\t<semantic_event transaction_id="%s" name="step_index">%s</semantic_event>' % (
                        ruuid, stepindex)

                interp = ''

                select = ''
                act = ''
                if (goalname is not None):
                    select = goalname
                else:
                    select = "undefined goal name"

                if (stepindex is not None):
                    act = stepindex
                else:
                    act = "undefined step index"
                semev = '\n\t\t\t<semantic_event transaction_id="%s" name="Tutor Turn" />' % (
                    ruuid)

                t = timeDS(row[colmap['time']])
                if concepts is not None:

                    conc = "<![CDATA[" + concepts + "]]>"
                else:
                    conc = "None"

                    # </meta>%(gse)s%(gise)s%(stse)s%(sise)s%(ae)s%(ta)s%(tskill)s%(sskill)s%(interp)s
                # if truth is not None or rawString is not None or tskill or sskill:
                if rawString is not None:
                    inputstring = "<![CDATA[" + rawString + "]]>"
                else:
                    inputstring = ""

                seqnum = seqnum + 1
                if ((stepname == "initiation") and (("[ent_txt]" in ta) or ("[continue]" in ta))):

                    if (probname != oldname):
                        cmuuid = uuidgen() #get a new context message id
                        cmdataset = """
                                      <dataset>
                                        <name>"SuperKCs - nR2Ndgated"</name>
                                        <level type="Scenario">
                                          <name>%(scenario)s</name>
                                          <problem tutorFlag="tutor">
                                            <name>%(probname)s</name>
                                          </problem>
                                            </level>
                                            </dataset>
                                      """ % locals()
                        cm = u"""
                        <context_message context_message_id="%(cmuuid)s" name="START_PROBLEM">
                            <meta>
                                <user_id anonFlag="true">%(uid)s</user_id>
                                <session_id>%(session)s</session_id>
                                <time>%(t)s</time>
                                <time_zone>%(tz)s</time_zone>
                            </meta>%(cmclass)s%(cmdataset)s
                        </context_message>
                        """ % locals()
                        xml += str(cm)
                        oldname = probname
                    
                        
                        


                    message = u"""
                    <tool_message context_message_id="%(cmuuid)s">
                        <meta>
                          <user_id anonFlag="true">%(uid)s</user_id>
                          <session_id>%(session)s</session_id>
                          <time>%(t)s</time>
                          <time_zone>%(tz)s</time_zone>
                        </meta>
                        <semantic_event transaction_id="%(ruuid)s" name="ATTEMPT"/>
                        <event_descriptor>
                          <selection>%(select)s</selection>
                          <action>%(act)s</action>
                          <input>%(stepname)s</input>
                        </event_descriptor>
                        <custom_field>
                            <name>Concepts</name>
                            <value>%(conc)s</value>
                        </custom_field>
                        <custom_field>
                            <name>SeqID</name>
                            <value>%(seqnum)s</value>
                        </custom_field>
                    </tool_message>
                    <tutor_message context_message_id="%(cmuuid)s">
                        <meta>
                            <user_id anonFlag="true">%(uid)s</user_id>
                            <session_id>%(session)s</session_id>
                            <time>%(t)s</time>
                            <time_zone>%(tz)s</time_zone>
                        </meta>
                        <semantic_event transaction_id="%(ruuid)s" name="RESULT" />
                        <event_descriptor>
                          <selection>%(select)s</selection>
                          <action>%(act)s</action>
                          <input>Press "Continue"</input>
                        </event_descriptor>
                        %(ae)s%(ta)s%(tskill)s%(sskill)s
                        <custom_field>
                            <name>SeqID</name>
                            <value>%(seqnum)s</value>
                        </custom_field>


                    </tutor_message>
                        """ % locals()
                tskill = ''
                sskill = ''

            else:
                ae = ''

                sskill = ''
                concepts = row[colmap['concepts']]
                #if row[colmap['truth_values']] is not None:
                 #   truth = row[colmap['truth_values']]
                  #  ae = "\n\t\t\t<action_evaluation>%s</action_evaluation>" % truthDS(truth)

                skclist = row[colmap['kclist']]
                if skclist is not None:
                    skc_sql = "SELECT kc from kchistory WHERE uuid='%s';" % row[colmap['uuid']]
                    skc_res = curs_s.execute(skc_sql)
                    for skc_row in skc_res:
                        ststringskill = skc_row[0]
                        spskill, stcategory = ststringskill.split(".")


                        if ((stcategory == "c") or (stcategory == "p") or (stcategory == "t") or (stcategory == "y")):
                            ae = "\n\t\t\t<action_evaluation>CORRECT</action_evaluation>"
                        elif ((stcategory == "w") or (stcategory == "b")):
                            ae = "\n\t\t\t<action_evaluation>INCORRECT</action_evaluation>"
                        else:
                            ae = "\n\t\t\t<action_evaluation>UNKNOWN</action_evaluation>"


                        stskill = superKCList[spskill]
                        sskill = sskill + "\t\t\t<skill><name>%s</name><category>student turn</category></skill>" % stskill

                if rawString is not None:
                    toolstring = "<![CDATA[" + rawString + "]]>"

                select = ''
                act = ''
                if (goalname is not None):
                    select = goalname
                else:
                    select = "undefined goal name"

                if (stepindex is not None):
                    act = stepindex
                else:
                    act = "undefined step index"

                if concepts is not None:
                    conc = "<![CDATA[" + concepts + "]]>"
                else:
                    conc = "None"
                seqnum = seqnum + 1
                ta = "\n\t\t\t<tutor_advice><![CDATA[%s]]></tutor_advice>" % feedback
                message = u"""
                <tool_message context_message_id="%(cmuuid)s">
                    <meta>
                      <user_id anonFlag="true">%(uid)s</user_id>
                      <session_id>%(session)s</session_id>
                      <time>%(t)s</time>
                      <time_zone>%(tz)s</time_zone>
                    </meta>
                    <semantic_event transaction_id="%(ruuid)s" name="RESPONSE"/>
                    <event_descriptor>
                      <selection>%(select)s</selection>
                      <action>%(act)s</action>
                      <input>%(toolstring)s</input>
                    </event_descriptor>
                    <custom_field>
                        <name>Concepts</name>
                        <value>%(conc)s</value>
                    </custom_field>
                    <custom_field>
                        <name>SeqID</name>
                        <value>%(seqnum)s</value>
                    </custom_field>
                </tool_message>
                <tutor_message context_message_id="%(cmuuid)s">
                    <meta>
                        <user_id anonFlag="true">%(uid)s</user_id>
                        <session_id>%(session)s</session_id>
                        <time>%(t)s</time>
                        <time_zone>%(tz)s</time_zone>
                    </meta>
                    <semantic_event transaction_id="%(ruuid)s" name="FEEDBACK" />
                    <event_descriptor>

                      <selection>%(select)s</selection>
                      <action>%(act)s</action>
                      <input>Free text answer</input>

                    </event_descriptor>
                    %(ae)s%(ta)s%(tskill)s%(sskill)s
                    <custom_field>
                        <name>SeqID</name>
                        <value>%(seqnum)s</value>
                    </custom_field>

                </tutor_message>
        """ % locals()

            if len(message):
                #        print message  # to capture more readable output
                xml += message
                messageCount += 1

        # if not len(xml) and messageCount:

        # if not (whatever == "whatever") and messageCount:
        if not firstrow and messageCount:
            sessions.append(xml.encode('utf-8'))
            # else:
            # firstrow = False

        result[uid] = sessions

        with open('output.xml', 'a') as the_file:
            for i in range(0, len(sessions)):
                the_file.write(str(sessions[i]))

                # print str(sessions[i])

    with open('output.xml', 'a') as the_file:
        the_file.write("</tutor_related_message_sequence>")

    # print result  # to capture the intended output081116

    # return result
    return ("lalalala")


def timeDS(t):
    """
  Translates a Unix time into the YYYY-MM-DD HH:MM:SS
  format required by DataShop.
  """

    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

    # return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def truthDS(val):
    """
  Translates our truth values into thos sort of understood by DS.
  Their CORRECT and INCORRECT are 'known' values.
  Unfortunately, DS has no notion of 'partial' (presumably because
  CTAT does not :^\ ) so we just use capitalized versions of these
  but DS will not know how to evaluate them. They are legal but opaque.
  """
    tvmap = {'yes': 'CORRECT', 'no': 'INCORRECT', 'yes': 'PARTIAL', 'unknown': 'UNKNOWN'}
    return tvmap.get(val, 'UNKNOWN')


def runsc(path):
    """
  Runs sc on the .sc file at 'path'.
  Returns a string with sc's output081116 to STDERR,
  which will be empty if sc did not encounter any errors.

  Since this command uses the -q flag, if there are difficulty levels
  that would require user interaction for ranking, sc will return an error
  message.
  """
    # fi,fo,fum = os.popen3("Compiler/sc -uq " + path)
    # fi.close()
    p = Popen("Compiler/sc -uq %s" % path,
              shell=True, stderr=PIPE, close_fds=True)

    # out = unicode(fum.read().decode('utf-8'))
    out = unicode(p.stderr.read().decode("utf-8"))
    # fo.close()
    # fum.close()
    while True:
        try:
            (pid, err) = os.waitpid(p.pid, os.WNOHANG)
        except:
            break
        if pid == 0:
            break
    return out


def xmllint(arg, fromFile=False):
    """
  Sends XML text to xmllint and returns xmllint's gripe,
  or an empty string if xml is well formed.
  If fromFile is False (the default), expects arg to be a string,
  this routine sends the XML via STDIN.
  Otherwise, arg is interpreted as a file path.
  """
    if fromFile:
        path = arg
    else:
        (fo, path) = tempfile.mkstemp()
        fo = open(path, 'w+')
        fo.write(arg)
        fo.close()
    # fi, foe = os.popen4("xmllint --noout --valid " + path)
    # fi.close()
    p = Popen("xmllint --noout --valid %s" % path,
              shell=True, stdout=PIPE, stderr=STDOUT, close_fds=True)
    # out = unicode(foe.read().decode('utf-8'))
    out = unicode(p.stdout.read().decode('utf-8'))
    # foe.close()
    while True:
        try:
            (pid, err) = os.waitpid(p.pid, os.WNOHANG)
        except:
            break
        if pid == 0:
            break
    if not fromFile:
        os.unlink(path)
    return out


def newFileInSameDir(file, extension):
    """
  Makes an absolute path based on 'file', strips off the
  extension(s), and adds the passed-in extension and returns it.
  """
    inpath = os.path.abspath(file)
    indir = os.path.dirname(inpath)
    infile = os.path.basename(inpath)
    inbase = infile
    while True:
        (inbase, ext) = os.path.splitext(inbase)
        if ext == '':
            break
    outbase = inbase
    return os.path.join(indir, outbase + extension)


def versionFromRCS(rcs):
    revFormatter = re.compile(r'\$Revision:+\s*', re.IGNORECASE)
    version = revFormatter.sub('v', rcs)
    revFormatter = re.compile(r'\s*\$\s*$', re.IGNORECASE)
    return revFormatter.sub('', version)


def expandScenario(path, experimenter=None):
    """
  Returns a dictionary with keys (path,xml,name,ext,fullname,experimenter):
    path is the absolute path to the passed-in file
    xml is the absolute path to the XML file (different from path if sc)
    name is the XML filename stripped of all extensions
    ext is the extension ('.xml' or '.sc')
    fullname is the full scenario name, like TuTalk-TestScenario-pam
    experimenter is the passed-in value, or the current user
  """
    d = dict()
    if experimenter is None:
        experimenter = pwd.getpwuid(os.getuid())[0]
    d['experimenter'] = experimenter
    path = os.path.abspath(path)
    d['path'] = path
    name = os.path.basename(path)
    # Iteratively trim off ALL the file extensions:
    # A monstrous name like 'Scenario.exe.jpeg.JPEG..xml' just becomes 'Scenario'
    while True:
        (name, ext) = os.path.splitext(name)
        if 'ext' not in d:
            d['ext'] = ext
        if ext == '':
            break
    d['name'] = name
    d['fullname'] = "TuTalk-%s-%s" % (name, experimenter)
    if d['ext'] == '.sc':
        # sc does the kind of ext trimming as we have done here.
        d['xml'] = os.path.join(os.path.dirname(path), name + '.xml')
    else:
        d['xml'] = d['path']
    return d


# ==========================================================
# ============== Experimenter Directory Stuff ==============
# Maintains Experimenter directory hierarchy and access to
# its scenario and logfiles, plus Coordinator lockfiles.
# Most all of these routines can raise IOError.
# ==========================================================
class ExperimentersDir:
    def __init__(self, tutalkDir, experimenter=None):
        self.tutalkDir = os.path.abspath(tutalkDir)
        if experimenter is None:
            experimenter = pwd.getpwuid(os.getuid())[0]
        self.experimentersDir = os.path.join(self.tutalkDir, 'Experimenters')
        self.experimenter = experimenter
        if not os.access(self.experimentersDir, os.F_OK):
            try:
                os.mkdir(self.experimentersDir)
            except Exception, why:
                raise IOError, "can't create experimenters directory at %s (%s)" % \
                               (self.experimentersDir, why)
        if experimenter is not None:
            self.experimenterDir(experimenter)

    def home(self):
        """
    Returns the absolute path to the directory in which TuTalk.py and
    Experimenters/ live.
    """
        return self.tutalkDir

    def path(self):
        """
    Returns the absolute path to the Experimenters/ directory.
    """
        return self.experimentersDir

    def experimenterDir(self, experimenter=None):
        if experimenter is None:
            experimenter = self.experimenter
        d = os.path.join(self.experimentersDir, experimenter)
        if not os.access(d, os.F_OK):
            try:
                os.mkdir(d)
            except Exception, why:
                raise IOError, "can't create experimenter directory at %s (%s)" % \
                               (d, why)
        return d

    def experimenterLogsDir(self, experimenter=None):
        return self.experimenterSubdir('logs', experimenter)

    def experimenterScenariosDir(self, experimenter=None):
        return self.experimenterSubdir('scenarios', experimenter)

    def experimenterSubdir(self, name, experimenter=None):
        experimenterDir = self.experimenterDir(experimenter)
        d = os.path.join(experimenterDir, name)
        if not os.access(d, os.F_OK):
            try:
                os.mkdir(d)
            except Exception, why:
                raise IOError, "can't create experimenter %s directory at %s (%s)" % \
                               (name, d, why)
        return d

    def lockfile(self, scenario):
        """
    Returns the full path to a lockfile for the given stripped scenario
    file name, using the implicit experimenter.
    Raises IOError if the file already exists.
    """
        lf = os.path.join(self.experimentersDir,
                          'TuTalk-%s-%s.lock' % (scenario, self.experimenter))
        if os.path.exists(lf):
            raise IOError, "lockfile '%s' exists; you are already running this scenario" % lf
        return lf


# ==========================================================
# ======================= XML STUFF ========================
# Common code for both the ScenarioReader and TuTalkReader.
# ==========================================================
class XMLErrorHandler:
    def __init__(self):
        self.err = ''

    def handler(self, ctx, msg):
        self.err += msg


# ==========================================================
# ===================== Socket STUFF =======================
# Code for safely reading from tutalkd sockets, to catch
# the CR-NL delimiter.
# ==========================================================
def tutalkdListener(socket, handler=None, exceptionHandler=None):
    th = threading.Thread(name="Incoming from tutalkd",
                          target=_tutalkdListenerLoop,
                          args=[socket],
                          kwargs={'handler': handler,
                                  'exceptionHandler': exceptionHandler})
    th.setDaemon(True)
    th.start()
    return th


def _tutalkdListenerLoop(sock, handler=None, exceptionHandler=None):
    completed = list()
    result = ''
    cr = False
    try:
        while True:
            tmp = sock.recv(1024)
            if not len(tmp):
                raise Exception, 'tutalkd has disconnected'
            for char in tmp:
                if char == '\n':
                    if cr:
                        completed.append(result)
                        result = ''
                    else:
                        result += char
                        cr = False
                elif char == '\r':
                    cr = True
                else:
                    cr = False
                    result += char
            while len(completed):
                xml = completed.pop()
                if not len(xml):
                    continue

                if handler is not None:
                    handler(xml)
    except Exception, why:
        if exceptionHandler is not None:
            exceptionHandler(why)


# ==========================================================
# ============== Ye olde DeferredException =================
# Monolithic TuTalk uses this to signal that a call will
# complete asynchronously.
# ==========================================================
class DeferredException(exceptions.Exception):
    "The operation will be deferred."
    pass


class ScenarioException(exceptions.Exception):
    "Could not parse scenario file."
    pass
