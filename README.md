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


#update the outcome to apply to initiations

update history
set truth_values = (select orighistory.truth_values from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.speaker="student" and history.speaker="system" and orighistory.time > history.time)

where 
exists 
(select * from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.speaker="student" and history.speaker="system" and orighistory.time > history.time)


#update the coverage to contatin tutor response -- we should add a column named feedback and add the tutor response there
update history
set coverage = (select orighistory.string from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.uid = history.uid and orighistory.speaker="system" and history.speaker="student" and orighistory.time >= history.time and orighistory.step_type="transition" and history.step_type="response")

where 
exists 
(select * from orighistory 
where orighistory.goal_index = history.goal_index and orighistory.uid = history.uid and orighistory.speaker="system" and history.speaker="student" and orighistory.time >= history.time and orighistory.step_type="transition" and history.step_type="response")