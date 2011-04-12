# -*- coding: utf-8 -*-
from twisted.internet import reactor,task, threads
from twisted.internet.protocol import ServerFactory, Protocol, ReconnectingClientFactory
from twisted.protocols.basic import NetstringReceiver
from twisted.application import internet, service
from twisted.web.client import getPage
import json
import ast
import weakref
import datetime
import os, sys
import netstring
import urllib
from termcolor import colored
from sys import stdout

""" DJANGO SUPPORT """
from django.core.management import setup_environ
#PATH = '%s/'%os.path.dirname(os.path.realpath(__file__))
PATH = '/home/jaime/energyspy/salcobrand/energyspy/'
sys.path.append(PATH)
os.environ['DJANGO_SETTINGS_MODULE'] = 'energyspy.settings'
#loading django setting
import settings
setup_environ(settings)
#loading django model references
from energyspy.viewer.models import *

creds  = {'jaime':'jaime','ricardo':'ricardo','felipe':'felipe'}

"""
COMMUNICATION ERROR_CODES
"""
ERROR_CODES = {
    0: 'No errors',
    10: 'credenciales de autenticacion invalidas',
    11: 'coordinador no registrado',
    12: 'Metodo no existe en servidor',
    13: 'Protocolo invalido',
    20: 'Algunos registros no sincronizaron correctamente',
    40: 'Timeout alcanzando durante webrequest en gateway',
    50: 'Error durante la notificación al webbrowser'
}

""" METHODS """
IDENTIFY_METHOD = 0
TOD_METHOD = 11
MAXQ_SYNC_METHOD = 99
MAXQ_UPDATE_DATETIME_METHOD = 97
MAXQ_GETTIME_METHOD = 27
RELE_UPDATE_STATES_METHOD = 25
ASYNC_SYNC_METHOD = 15
ECHO_METHOD = 70

def formatExceptionInfo(maxTBlevel=5):
    cla, exc, trbk = sys.exc_info()
    excName = cla.__name__
    try:
        excArgs = exc.__dict__["args"]
    except KeyError:
        excArgs = "<no args>"
    excTb = traceback.format_tb(trbk, maxTBlevel)
    return (excName, excArgs, excTb)

class arduinoRPC(Protocol):
    def connectionMade(self):
        """ Append connection to client list """
        print 'Conectando'

    def connectionLost(self, reason):
        print reason
        """ mac address is searched and all reference to self.factory.clientes are erased """
        for gw_id in self.factory.references.keys():
            if self.factory.references[gw_id]['handler']() == self:
                print 'Connection closed - GW_ID: %s'%gw_id
                del self.factory.references[gw_id]

                d1 = threads.deferToThread(Coordinatorlogout,[],**{'gw_id':gw_id})
                d1.addCallbacks(genericCallback,genericCallback)
                self.factory.clients.remove(self)

    def dataReceived(self,data):

        """ Every data received is passed to a function """
        try:
            print colored("%s // %s "%(','.join(['%s'%ord(i) for i in data]),data), 'green')
        except:
            print colored("%s "%','.join(['%s'%ord(i) for i in data]), 'green')
            
        method,params,id = self.parse(data)
        data = []
        
        
        if method == 'FUCK, WAIT PLEASE':
            """ wait for the next task call  """
            pass
        elif method == 5:
            """ remove id item from queue """
            for index,request in enumerate(self.factory.webRequestQueue):
                if request['opID'] == id:
                    print colored('Web Request Operation %s in gateway id %d is completed'%(request['webopID'],request['gw_id']),'yellow')
                    self.factory.webRequestQueue.pop(index)
                    #useful to check if opID has been served when orbited is nos connected
                    print colored('Changing PushService object state linked to processed webopID','yellow')
                    d1 = threads.deferToThread(NotifyServerofTaskCompleted,[],**{'webopID':request['webopID'],'gw_id':request['gw_id']})
                    d1.addCallbacks(genericCallback,genericCallback)
                    
        else:
            self.getFunction(method,params,id)
        
    def parse(self,data):
        try:
            #echo
            if data== '0:':
                #print 'Echo'
                return '0', [], False
            
            dataDict = [ord(i) for i in data]
            method = dataDict[0]
            params = dataDict[1:len(dataDict)-1]
            opID = dataDict[len(dataDict)-1]
            params_pt = dataDict[1]
            return method,params,opID
        except:
            return False,False,False
    
    def getFunction(self,method,args,id):
        """
        IDENTIFY_METHOD = 1
        TOD_METHOD = 11
        MAXQ_SYNC_METHOD = 99
        MAXQ_UPDATE_DATETIME_METHOD = 97
        MAXQ_GETTIME_METHOD = 27
        RELE_UPDATE_STATES_METHOD = 25
        ASYNC_SYNC_METHOD = 15
        ECHO_METHOD = 70
        """
        try:
            a = getattr(self,'jsonrpc_%s'%{0:'identify',11:'get_TOD',99:'sync_maxq',25:'update_relay_state',15:'sync_async',27:'getTime',97:'getTimeMAXQ',69:'gateway_failure',70:'echo'}[method])
        except:
            print colored("Method not recognized", 'red')
            return
        
        if a:
            #try:
            value_to_return = a(id,*args)
            #return value_to_return
            #except:
            #    print colored('Error in method execution','red')
            return 
        else:
            self.transport.write(json.dumps({'error':12,'id':id}))
            return False
    
    """ REMOTE METHODS """
    def jsonrpc_echo(self,id,*args):
        if self in self.factory.clients:
            toSend = ''.join([chr(i) for i in [ECHO_METHOD,1,0,id]])
            try:
                print colored("%s // %s "%(','.join(['%s'%ord(i) for i in toSend]),toSend), 'magenta')
            except:
                print colored("%s "%','.join(['%s'%ord(i) for i in toSend]), 'magenta')
            
            self.transport.write(toSend)
        else:
            print 'No autentificado'
    def jsonrpc_gateway_failure(self,id,*args):
        for gw_id in self.factory.references.keys():
            if self.factory.references[gw_id]['handler']() == self:
                print colored('GATEWAY ID: %s RESET'%gw_id,'yellow')

                d1 = threads.deferToThread(logGatewayReset,[],**{'gw_id':gw_id})
                d1.addCallbacks(genericCallback,genericCallback)
                
    def jsonrpc_update_relay_state(self,id,*args):
        if self in self.factory.clients:
            print colored('UPDATE RELAYS','yellow')
            act_id  = args[0]
            states  = args[1:len(args)]
            for gw_id in self.factory.references.keys():
                if self.factory.references[gw_id]['handler']() == self:
                    break

            dictToSend = threads.deferToThread(updateRelaysStateonDjango,[],**{'act_id':act_id,'states':states,'obj':self,'id':id,'gw_id':gw_id})
            dictToSend.addCallbacks(genericCallback,genericCallback)
    
    def jsonrpc_get_TOD(self,id,*args):
        if self in self.factory.clients:
            print colored('GETTING TOD','yellow')
            MSB = (args[0]<<24) + (args[1]<<16) +(args[2]<<8)+(args[3])
            LSB = (args[4]<<24) + (args[5]<<16) +(args[6]<<8)+(args[7])
            mac = ("%s%s"%(hex(MSB).replace('0x',''),hex(LSB).replace('0x',''))).upper()
            dictToSend = threads.deferToThread(sendIDsToGateway,[],**{'mac':mac,'obj':self,'id':id})
            dictToSend.addCallbacks(genericCallback,genericCallback)
            #'-'.join(['%s'%i[0] for i in Devices.objects.filter(mac=mac).values_list('id')])
        
    def jsonrpc_identify(self,id,*args):
        mac_string = ('%s'%list(args)).replace(' ','')
        
        #query to django database
        dictToSend = threads.deferToThread(Coordinatorlogin,[],**{'mac':mac_string,'obj':self,'id':id})
        dictToSend.addCallbacks(genericCallback,errorLogin)
    

    def jsonrpc_sync_async(self,id,*args): #temp and lighting
        import struct
        if self in self.factory.clients:
            
            print colored('SYNC_ASYNC','yellow')
            device = args[0]
            
            if not (self in self.factory.clients):
                print 'Your are not authenticated'
                self.transport.loseConnection('Your are not authenticated')
            
            datetimestamp = datetime.datetime.now()
    
            measurements = args[1:]

            dictToSend = threads.deferToThread(syncASYNC,[],**{'device':device,'datetimestamp':datetimestamp,'measurements':measurements,'obj':self,'id':id})
            dictToSend.addCallbacks(genericCallback,genericCallback)
    def jsonrpc_getTime(self,id,*args):
        if self in self.factory.clients:
            now = datetime.datetime.now();
            toSend = ''.join([chr(i) for i in [MAXQ_GETTIME_METHOD,5,now.year-2000,now.month,now.day, now.hour,now.minute,id]])
            try:
                print colored("%s // %s "%(','.join(['%s'%ord(i) for i in toSend]),toSend), 'magenta')
            except:
                print colored("%s "%','.join(['%s'%ord(i) for i in toSend]), 'magenta')
            
            self.transport.write(toSend)
    
    def jsonrpc_getTimeMAXQ(self,id,*args):
        if self in self.factory.clients:
            now = datetime.datetime.now();
            toSend = ''.join([chr(i) for i in [MAXQ_UPDATE_DATETIME_METHOD,5,now.year-2000,now.month,now.day, now.hour,now.minute,id]])
            try:
                print colored("%s // %s "%(','.join(['%s'%ord(i) for i in toSend]),toSend), 'magenta')
            except:
                print colored("%s "%','.join(['%s'%ord(i) for i in toSend]), 'magenta')
            
            self.transport.write(toSend)
            
    def jsonrpc_sync_maxq(self,id,*args):
        import struct
        if self in self.factory.clients:
            
            print colored('SYNC_MAXQ','yellow')
            device = args[0]
            datetime_data = args[1:6]
            """raw_data[0:4]: date time stamp"""
            """raw_data[5:]_ measurements """
            if not (self in self.factory.clients):
                print 'Your are not authenticated'
                self.transport.loseConnection('Your are not authenticated')
                return 
            #try:
            datetimestamp = datetime.datetime(datetime_data[0]+2000,datetime_data[1],datetime_data[2],datetime_data[3],datetime_data[4])
            now = datetime.datetime.now()
            delta_max = datetime.timedelta(days=1) # se acepta datos con un desfase maximo de reloj con el servidor de 10 minutos
            if ((now - datetimestamp) > delta_max) or ((datetimestamp-now) > delta_max):
                print colored("(Date)MaxQ bad data","red")
                packet = ''.join(chr(i) for i in [MAXQ_SYNC_METHOD,1,0,id])
                try:
                    print colored("%s // %s "%(','.join(['%s'%ord(i) for i in packet]),packet), 'magenta')
                except:
                    print colored("%s "%','.join(['%s'%ord(i) for i in packet]), 'magenta')
                return
            """except:            
                print colored("MaxQ bad data",'red')
                toSend = ''.join([chr(i) for i in [MAXQ_SYNC_METHOD,1,254,id]])
                self.transport.write(toSend)
                return"""
                
            measurements_long_raw_data = ''.join([chr(i) for i in args[6:]]) 
            measurements = list(struct.unpack(">24l",measurements_long_raw_data))
            #measurements = measurements

            dictToSend = threads.deferToThread(syncMAXQ,[],**{'device':device,'datetimestamp':datetimestamp,'measurements':measurements,'obj':self,'id':id})
            dictToSend.addCallbacks(genericCallback,genericCallback)
        


class rpcFactory(ServerFactory):
    protocol = arduinoRPC
    
    def __init__(self,root,name):
        print "Micros remote RPC server on port 7081 started"
        self.root = root
        self.name = name
        self.clients    =   [] #[object1, object2,...]
        self.references =   {} #gw_ids: {handler:weak_ref -> object,webrequest:[{id:opID1, data:data1, state:'WAIT_ACK', time_requested:timestamp},{id:opID2, data:data2,state:'WAIT'},...]} 
        self.webRequestQueue  =   [] #[{gw_id:gw_id1,opID:opID1,data:data1,state:WAIT_ACK, time_requested:timestamp},{gw_id:gw_id2,opID:opID2,data:data2,state:WAIT},...]
        """ task called when busy-queue has some items, retry request to 
        gateway when this has send a method=busy"""
        self.timeoutRequestToGateway    =    60 #seg
        self.recallWhenGatewayBusy = task.LoopingCall(self.Task_retryRequestToGateway)
        self.recallWhenGatewayBusy.start(2)
        print 'Web request QUEUE checker started'
        
    def Task_retryRequestToGateway(self):
        import random
        listas = esperando_ack = 0
        ids = []
        for i in self.webRequestQueue:
            if i['state'] == 'WAIT_ACK':
                ids.append(i['opID'])
                
            if i['state'] == 'WAIT':
                listas +=1
            if i['state'] == 'WAIT_ACK':
                esperando_ack +=1

        for index,request in enumerate(self.webRequestQueue):  #request contains, packet, webopID, state
            print colored('Reglas de control lista para enviar (%d)\nReglas de control esperando ACKS (%d) '%(listas, esperando_ack),'yellow')
            now = datetime.datetime.now()
            state   =   request['state']
            print request
            if state == 'WAIT':  #first time to be served
                #request['data'][1] =  random.randint(0, 255) // create a randomin distintinto al replicado en caso que sea igual a uno en espera
                #packetToSend   = request['data'].encode('ascii')
                
                packetToSend   = request['data']
                nomore_ids_accepted = True
                for i in range(1,255):
                    if not i in ids:
                        opID = i
                        nomore_ids_accepted = False
                        break

                print 'ioID %s'%opID
                if nomore_ids_accepted:
                    print 'no more ids accepted'
                    continue # let's process next one, maybe later there is a slot available
                
                if not (request['gw_id'] in self.references.keys()):
                    print 'Gateway desconectado ... esperando reconexion'
                    continue
                
                request.update({'opID':opID,'try':1})
                
                packetToSend.append(opID)
                
                print colored('(TRY:%d) Sending data (%s) to gateway %d (%s) (TG : %s, BT: %s) '%(request['try'],packetToSend,request['gw_id'], now.strftime('%H:%M:%S'),request['webopID'],request['opID']),'magenta')
                
                self.references[request['gw_id']]['handler']().transport.write(''.join([chr(l) for l in packetToSend]))
                self.webRequestQueue[index]['state'] = 'WAIT_ACK'
                self.webRequestQueue[index]['time_requested'] = now
                
            elif state == 'WAIT_ACK':  #request already sent and waiting ack from gateway, if timeout set ERROR
                TIMEOUT = datetime.timedelta(seconds=self.timeoutRequestToGateway)
                if (request['time_requested'] + TIMEOUT < now):
                    """ set TIMEOUT ERROR and notify to browser"""
                    if request['try'] < 3:
                        request['try'] = request['try'] + 1
                        request['time_requested'] = now
                        packetToSend   = request['data']
                        packetToSend.append(request['opID'])
                        print colored('(TRY:%d) Sending data (%s) to gateway %d (%s) (TG : %s, BT: %s) '%(request['try'],packetToSend,request['gw_id'], now.strftime('%H:%M:%S'),request['webopID'],request['opID']),'magenta')
                        self.references[request['gw_id']]['handler']().transport.write(''.join([chr(l) for l in packetToSend]))
                    else: 
                        print 'Timeout (TG : %s, BT: %s)'%(request['webopID'],request['opID'])
                        self.webRequestQueue.pop(index)
                        d1 = threads.deferToThread(NotifytoBrowserofConnectionTimeout,[],**{'webopID':request['webopID'],'gw_id':request['gw_id']})
                        d1.addCallbacks(genericCallback,genericCallback)
                    
                        # this would be useful when browser by timeout can check the opID status 
                        # directly thorugh a django url request
                        break #prevent iteration corrupt start again is better
            elif state == 'ERROR': #if error was received from gateway
                pass

class djangoProtocol(Protocol):
    def connectionMade(self):
        print 'Conexion desde celery'
        self.factory.clients.append(self)
    def connectionLost(self,reason):
        print 'Saliendo',reason
    def parse(self,data):
        try:
            dataDict = json.loads(data)

            return dataDict['method'],dataDict['params'],dataDict['webopID']
        except:
            self.transport.write(json.dumps({'error':13})) 
            return False,False,False
    
    def dataReceived(self,data):
        print colored("Recibiendo desde django %s "%data, 'red') 
        method, params, webopID = self.parse(data)
        
        if method == 'PushService':
            params.update({'state':'WAIT','webopID':webopID})
            
            #attach data to be send to gateway(arduino) target
            self.factory.root.servers['Arduino RPC server'].webRequestQueue.append(params) # params:{gw_id:gw_id1,opID:opID1,data:data1,state:WAIT}
            #ack to celery
            print colored({'method':'ack','webopID':webopID},'red')
            self.transport.write(json.dumps({'method':'ack','webopID':webopID})) # data puched to queue, when data is laoded and acked by twister a callback with notification will be sent to django to push orbited notification to browser
        else:
            self.connectionLost('Bad request from django')

class djangoFactory(ServerFactory):
    
    protocol = djangoProtocol 
    
    def __init__(self,root,name):
        self.root = root
        self.name = name     
        self.clients = [] #only one client (def sendDataToGateway())  
        print "Django Handler on port 6969 started " 

class Container():
    def __init__(self):
        self.servers = {}
    def add_server(self,obj,name):
        self.servers[name] = obj(self,name)



"""Callbacks"""

#DJANGO NOTIFICATION 
def Coordinatorlogin(*args,**kwargs):
    mac = kwargs['mac']
    obj = kwargs['obj']
    id = kwargs['id']

    
    query =   Coordinators.objects.filter(mac=mac)

    if query:
        coordinator = query[0]
        dictToSend  = {'results':{'gw_id':coordinator.id},'error':0,'id':id}
        obj.factory.clients.append(obj)
        obj.factory.references[coordinator.id] = {'handler':weakref.ref(obj)}
        print colored('Coordinador ID %s authenticaded'%(dictToSend['results']['gw_id']),'yellow')
        coordinator.status = '1'
        coordinator.save()
        #log coordinator event
        a=Events()
        a.is_coordinator = True
        a.coordinator = coordinator
        a.time = datetime.datetime.now()
        a.section = Sections.objects.filter(main_sensor__coordinator = coordinator)[0]
        a.details = 'Gateway conectado'
        a.save()
        dataToNotify = {'params':{'gw_id':coordinator.id, 'state':'online','event_details':[a.time.strftime('%Y-%m-%d %H:%M:%S'), a.section.name,'Gateway',a.details]},'method':'gw_activity','id':1}
        encodedData = urllib.urlencode({'data':dataToNotify})
        
        print colored('sending gateway online notification','yellow')
        d = getPage('http://salcobrand.energyspy.cl/notify_to_webclient?%s'%encodedData)
        d.addCallbacks(cSuccessGetPage,cErrorGetPage)
        toSend_data = [IDENTIFY_METHOD,3,123,0,23,id]
        toSend_ascci = ''.join([chr(i) for i in toSend_data])
        try:
            print colored("%s // %s "%(','.join(['%s'%ord(i) for i in toSend_ascci]),toSend_ascci), 'magenta')
        except:
            print colored("%s "%','.join(['%s'%ord(i) for i in toSend_ascci]), 'magenta')
        
        obj.transport.write(toSend_ascci)

    else:
        dictToSend  = {'results':{},'error':11,'id':id}
        print 'Coordinator not found'
    
    dataToSend  = "%s:%s:%s"%(dictToSend['id'],dictToSend['results']['gw_id'],dictToSend['error'])
    #obj.transport.write(dataToSend)
    return dictToSend

def logGatewayReset(*args,**kwargs):
    gw_id = kwargs['gw_id']
    coordinator = Coordinators.objects.filter(pk=gw_id)[0]
    coordinator.save()
    a=Events()
    a.is_coordinator = True
    a.coordinator = coordinator
    a.section = Sections.objects.filter(main_sensor__coordinator = coordinator)[0]
    a.time = datetime.datetime.now()
    a.details = 'Reset de Gateway'
    a.save()
    return True
    
def Coordinatorlogout(*args, **kwargs):
    gw_id = kwargs['gw_id']
    coordinator = Coordinators.objects.filter(pk=gw_id)[0]
    coordinator.status = '0'
    coordinator.save()
    a=Events()
    a.is_coordinator = True
    a.coordinator = coordinator
    a.section = Sections.objects.filter(main_sensor__coordinator = coordinator)[0]
    a.time = datetime.datetime.now()
    a.details = 'Gateway desconectado'
    a.save()
    dataToNotify = {'params':{'gw_id':coordinator.id, 'state':'offline','event_details':[a.time.strftime('%Y-%m-%d %H:%M:%S'), a.section.name,'Gateway',a.details]},'method':'gw_activity','id':1}
    encodedData = urllib.urlencode({'data':dataToNotify})
    d = getPage('http://salcobrand.energyspy.cl/notify_to_webclient?%s'%encodedData)
    d.addCallbacks(cSuccessGetPage,cErrorGetPage)
    return True

def NotifytoBrowserofConnectionTimeout(*args, **kwargs):
    gw_id = kwargs['gw_id']
    webopID = kwargs['webopID']
    print 'Sending orbited confirmation to browser'
    coordinator = Coordinators.objects.filter(pk=gw_id)[0]
    a=Events()
    a.is_coordinator = True
    a.coordinator = coordinator
    a.section = Sections.objects.filter(main_sensor__coordinator = coordinator)[0]
    a.time = datetime.datetime.now()
    a.details = 'Gateway no responde Timeout'
    a.save()
    dataToNotify = {'params':{'gw_id':coordinator.id, 'state':'timeout','webopID':webopID,'event_details':[a.time.strftime('%Y-%m-%d %H:%M:%S'), a.section.name,'Gateway',a.details]},'method':'gw_timeout','id':1}
    encodedData = urllib.urlencode({'data':dataToNotify})
    d = getPage('http://salcobrand.energyspy.cl/notify_to_webclient?%s'%encodedData)
        
    

def NotifyServerofTaskCompleted(*args,**kwargs):
    gw_id = kwargs['gw_id']
    webopID = kwargs['webopID']
    try:
        a=PushService.objects.filter(opID=webopID.encode('ascii'))
        if a:
            a[0].completed = True
            print colored('Changing PushService items to complete status','yellow')
            a[0].save()
            print colored('Task %s completed'%webopID,'yellow')
    except:
        print colored('webopID no encontrado','yellow')
        
     
def errorLogin(data):
    print data
    print 'Error during login procedure'
    dictToSend  = {'results':{},'error':11,'id':id}
    return dictToSend

def stripcomments(text):
    import re
    text   =   text.replace('\n','')
    text   =   text.replace('\r','')
    text   =   text.replace('\t','')
    return re.sub('//.*?\n|/\*.*?\*/', '', text, re.S)

def updateRelaysStateonDjango(*args,**kwargs):

    act_id = kwargs['act_id']
    gw_id   = kwargs['gw_id']
    states = kwargs['states']
    obj = kwargs['obj']
    id  = kwargs['id']
    #mula
    po = Devices.objects.filter(pk=int(act_id))
    actuator = Devices.objects.filter(mac=po[0].mac,typeofdevice__type='Actuator')
    if not actuator:
        print colored('Device no existe o no compatible','red')
        return
    registers = ast.literal_eval(stripcomments(actuator[0].registers))
    if registers['signals_connected'].has_key('IO1'): #lighting actuator (IO1..IO6)
        lighting_device = actuator[0]
        registers_lighting = registers
        hvac_device = actuator[1]
        registers_hvac = ast.literal_eval(stripcomments(hvac_device.registers))
    else: # hvac actuator (IO7..IO12)
        lighting_device = actuator[1]
        registers_lighting = ast.literal_eval(stripcomments(lighting_device.registers))
        hvac_device = actuator[0]
        registers_hvac = registers

    #print colored('(%s) updating relays on Django DB: (%s)'%(id,actuator[0].name),'yellow')
    
    event_details = {'act_id':act_id,'IOs':[]}
    num_ios = 12
    something_to_notify_lighting = False
    something_to_notify_hvac = False
    
    for i,val in enumerate(states):
        if i == num_ios:
            print colored('Paquete de reles corrupto, ignorando datos de mas','yellow')
            break
        IOtag = 'IO%s'%(i+1)
        
        if i<6: # lighting registers
            currentState = registers_lighting['signals_connected'][IOtag]['state']
            Title = registers_lighting['signals_connected'][IOtag]['Title']
        else: #hvac registers
            currentState = registers_hvac['signals_connected'][IOtag]['state']
            Title = registers_hvac['signals_connected'][IOtag]['Title']
            
        try:
            newState = {0:False,1:True}[val]
        except:
            continue

        di = {False:'Apagado',True:'Encendido'}
    
        if currentState != newState:
            
            event_details['IOs'].append({IOtag:{'state':newState,'Title':Title}})
                
            #print colored('%s %s -> %s'%(registers['signals_connected'][IOtag]['Title'].encode('utf8'),di[currentState],di[newState]),'yellow')
            if i<6:
                something_to_notify_lighting = True
                registers_lighting['signals_connected'][IOtag]['state']= {0:False,1:True}[val]
            else:
                something_to_notify_hvac = True
                registers_hvac['signals_connected'][IOtag]['state']= {0:False,1:True}[val]
            
    dataToSend = ''.join([chr(i) for i in [RELE_UPDATE_STATES_METHOD,1,0,id]])
    try:
        print colored("%s // %s "%(','.join(['%s'%ord(i) for i in dataToSend]),dataToSend), 'magenta')
    except:
        print colored("%s "%','.join(['%s'%ord(i) for i in dataToSend]), 'magenta')
        
    obj.transport.write(dataToSend)
    
    #creating events and send them to web browser
    
    if something_to_notify_hvac or something_to_notify_lighting:
        #saving lighting relay registers
        if something_to_notify_lighting:
            lighting_device.registers = registers_lighting
            lighting_device.save()
        else:
            #saving hvac relay registers
            hvac_device.registers = registers_hvac
            hvac_device.save()
        
        print colored('Update relays state on WEB browser using orbited','yellow')
        #create packet to notificate browser via
        coordinator = Coordinators.objects.filter(pk=gw_id)[0]
        a=Events()
        a.is_coordinator = False
        a.coordinator = coordinator
        a.section = Sections.objects.filter(main_sensor__coordinator = coordinator)[0]
        a.time = datetime.datetime.now()
        a.details = event_details
        if something_to_notify_lighting:
            a.device = lighting_device
        else:
            a.device = hvac_device

            
        a.save()
        print 'Evt ID: %s'%a.id
        
        
        dataToNotify = {'params':{'gw_id':coordinator.id,'event_details':[a.time.strftime('%Y-%m-%d %H:%M:%S'), a.section.name,a.device.name,a.details]},'method':'update_relays','id':1}
        encodedData = urllib.urlencode({'data':dataToNotify})
        d = getPage('http://salcobrand.energyspy.cl/notify_to_webclient?%s'%encodedData)
    

def sendIDsToGateway(*args,**kwargs):
    mac = kwargs['mac']
    obj = kwargs['obj']
    id = kwargs['id']
    all_slots = Devices.objects.filter(mac=mac)
    slots_dict = {}
    type_dict = {'RLS8':2,'MAXQ':1,'TMP':3,'LGH':4}
    for dev in all_slots:
        if not slots_dict.has_key(dev.slots):
            slots_dict[dev.slots] = [] 
        slots_dict[dev.slots].append([dev.id,type_dict[dev.typeofdevice.name]])
    num_slots = len(slots_dict)
    ids = []
    f = []
    for slot_index in range(1,num_slots+1,1):
        num_ids = len(slots_dict[slot_index])
        ids = ids + [num_ids]
        f= []
        for it in slots_dict[slot_index]:
            f.append(it[0])
            f.append(it[1])
        ids = ids + f

    packet = [TOD_METHOD] + [len([num_slots] + ids)] + [num_slots] + ids + [id]
    packet_ascci = ''.join([chr(i) for i in packet])
    
    try:
        print colored("%s // %s "%(','.join(['%s'%ord(i) for i in packet_ascci]),packet_ascci), 'magenta')
    except:
        print colored("%s "%','.join(['%s'%ord(i) for i in packet_ascci]), 'magenta')
    
    obj.transport.write(packet_ascci)

def syncASYNC(*args,**kwargs): 
    device = kwargs['device']
    measurements = kwargs['measurements']
    datetimestamp = kwargs['datetimestamp']
    obj = kwargs['obj']
    id = kwargs['id']
    #try:
    newdata = Measurements()
    newdata.sensor = Devices.objects.get(pk=int(device))
    newdata.datetimestamp = datetimestamp
    newdata.type = 'Sensor'
    newdata.slot = newdata.sensor.slots
    
    if newdata.sensor.typeofdevice.name == 'TMP':
        print colored("Temperature packet")
        newdata.T00 = measurements[0]/2.0
        newdata.T01 = measurements[1]/2.0
        newdata.T02 = measurements[2]/2.0
        newdata.T03 = measurements[3]/2.0
        newdata.T04 = measurements[4]/2.0
        newdata.T05 = measurements[5]/2.0
    
    if newdata.sensor.typeofdevice.name == 'LGH':
        print colored("Lighting packet")
        newdata.L00 = measurements[0]
        newdata.L01 = measurements[1]
        newdata.L02 = measurements[2]
        newdata.L03 = measurements[3]
        newdata.L04 = measurements[4]
        newdata.L05 = measurements[5]
        
    packet = ''.join(chr(i) for i in [ASYNC_SYNC_METHOD,1,0,id])
    print colored("Nueva medicion %s" % newdata.__dict__,'yellow')
    try:
        print colored("%s // %s "%(','.join(['%s'%ord(i) for i in packet]),packet), 'magenta')
    except:
        print colored("%s "%','.join(['%s'%ord(i) for i in packet]), 'magenta')
        
    obj.transport.write(packet)
    #except:
    #    print colored('ERROR SYNC ASYNC','yellow')

def syncMAXQ(*args,**kwargs): 
    device = kwargs['device']
    measurements = kwargs['measurements']
    datetimestamp = kwargs['datetimestamp']
    obj = kwargs['obj']
    id = kwargs['id']
    try:
        
        newdata = Measurements()
        newdata.sensor = Devices.objects.get(pk=int(device))
        corrections = ast.literal_eval(stripcomments(newdata.sensor.board.corrections))
        newdata.datetimestamp = datetimestamp
        newdata.type = 'Sensor'
        newdata.slot = newdata.sensor.slots
    
        newdata.V1RMS = measurements[0]/10.0 * corrections['VOLT_CC']
        newdata.V2RMS = measurements[1]/10.0 * corrections['VOLT_CC']
        newdata.V3RMS = measurements[2]/10.0 * corrections['VOLT_CC']
        
        newdata.I1RMS = measurements[3]/10.0 * corrections['AMP_CC']
        newdata.I2RMS = measurements[4]/10.0 * corrections['AMP_CC']
        newdata.I3RMS = measurements[5]/10.0 * corrections['AMP_CC']
        
        newdata.PWRP_A = measurements[6]/10.0 * corrections['PWR_CC']
        newdata.PWRP_B = measurements[7]/10.0 * corrections['PWR_CC']
        newdata.PWRP_C = measurements[8]/10.0 * corrections['PWR_CC']
        
        newdata.PWRQ_A = measurements[9]/10.0 * corrections['PWR_CC']
        newdata.PWRQ_B = measurements[10]/10.0 * corrections['PWR_CC']
        newdata.PWRQ_C = measurements[11]/10.0 * corrections['PWR_CC']
        
        newdata.PWRS_A = measurements[12]/10.0 * corrections['PWR_CC']
        newdata.PWRS_B = measurements[13]/10.0 * corrections['PWR_CC']
        newdata.PWRS_C = measurements[14]/10.0 * corrections['PWR_CC']
        
        newdata.ENRP_A = measurements[15]/10.0 * corrections['ENR_CC']
        newdata.ENRP_B = measurements[16]/10.0 * corrections['ENR_CC']
        newdata.ENRP_C = measurements[17]/10.0 * corrections['ENR_CC']
        
        newdata.PF_A = measurements[18]*0.00001
        newdata.PF_B = measurements[19]*0.00001
        newdata.PF_C = measurements[20]*0.00001
        
        newdata.AEOVER = measurements[21] 
        newdata.BEOVER = measurements[22]
        newdata.CEOVER = measurements[23]
        
        newdata.save()

        packet = ''.join(chr(i) for i in [MAXQ_SYNC_METHOD,1,0,id])
        print colored("Nueva medicion %s" % newdata.__dict__,'yellow')
        try:
            print colored("%s // %s "%(','.join(['%s'%ord(i) for i in packet]),packet), 'magenta')
        except:
            print colored("%s "%','.join(['%s'%ord(i) for i in packet]), 'magenta')
        
        obj.transport.write(packet)
    except:
        print colored('ERROR SYNC MAXQ','yellow')
        packet = ''.join(chr(i) for i in [MAXQ_SYNC_METHOD,1,0,id])
        try:
            print colored("%s // %s "%(','.join(['%s'%ord(i) for i in packet]),packet), 'magenta')
        except:
            print colored("%s "%','.join(['%s'%ord(i) for i in packet]), 'magenta')
        
    
    
    
    
def cSuccessGetPage(data):
    try:
        a=ast.literal_eval(data)
        print ERROR_CODES[a['error']]
        print colored("Stomp notification of coordinator login COMPLETED",'yellow')
        return True
    except:
        print colored('Error during notification to django server','yellow')
        return False
        
def cErrorGetPage(failure):
    print failure
    print colored("Stomp notification of coordinator login FAILED",'yellow')
    return False

def genericCallback(data):
    return data

container = Container()
container.add_server(djangoFactory,'Django Framework Handler')
container.add_server(rpcFactory,'Arduino RPC server')

#reactor.listenTCP(6969, container.servers['Django Framework Handler'])
#reactor.listenTCP(7081, container.servers['Arduino RPC server'])

djangoservice = internet.TCPServer(6969, container.servers['Django Framework Handler']) # create the service
rpcservice = internet.TCPServer(7081, container.servers['Arduino RPC server']) # create the service

application = service.Application("twistes router for arduinos")

rpcservice.setServiceParent(application)
djangoservice.setServiceParent(application)

#reactor.listenTCP(7080, container.servers['Django Framework Handler'])
#reactor.listenTCP(7081, container.servers['Arduino RPC server'])

#reactor.run()

