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
