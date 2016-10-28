# toDatashop
MATD import data to Datashop

This Python script reads TuTalk data from an sqlite database and creates a Datashop xml file 

---------------------------------------------------------------------------------------
How to run


In Python console:

>>> from toDatashop import databaseToDataShop
>>> databaseToDataShop("dialogue-history-nR2Ndgated.db")

where:
toDatashop : the name of the python script
dialogue-history-nR2Ndgated.db: the name of the database

*note: this script is for SQLITE databases*

---------------------------------------------------------------------------------------
Database preparation:

---------------------------------------------------------------------------------------
BEFORE running the script execute the following SQL queries:


#create new table as a copy of an existing one

create table orighistory as
select * from history


#fill the NULLS fix
update orighistory

set goal_index = (select history.goal_index from history
where history.time_out ISNULL and history.speaker = "student" and history.uid = orighistory.uid and (orighistory.time - history.time) <=5)

where exists
(select * from history
where history.time_out ISNULL and history.speaker = "student" and history.uid = orighistory.uid and (orighistory.time - history.time) <=5) and
orighistory.goal_index ISNULL


update orighistory
set step_type="transition"
where orighistory.speaker="system" and orighistory.goal_index NOTNULL and orighistory.goal_name ISNULL


#update the outcome to apply to initiations / ONLY FOR THE  inherit version

update history
set truth_values = (select orighistory.truth_values from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.speaker="student" and history.speaker="system" and orighistory.time > history.time)

where 
exists 
(select * from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.speaker="student" and history.speaker="system" and orighistory.time > history.time)


#update the coverage to contatin tutor response (aka feedback) -- we should add a column named feedback and add the tutor response there
update history
set coverage = (select orighistory.string from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.uid = history.uid and orighistory.speaker="system" and history.speaker="student" and (orighistory.time - history.time <=10) and orighistory.step_type="transition" and history.step_type="response")

where
exists
(select * from orighistory
where orighistory.goal_index = history.goal_index and orighistory.uid = history.uid and orighistory.speaker="system" and history.speaker="student" and (orighistory.time - history.time <=10) and orighistory.step_type="transition" and history.step_type="response")

