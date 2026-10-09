"""Wire schemas shared by both SDK 1.x and Hermes' managed SDK 2.x processes."""
from ...desktop_input import DesktopAction
COMPUTER_METHODS=('computer.status','computer.observe','computer.input')
COMPUTER_TOOLS=[{'name':'wearing_computer_observe','description':'观察已配对电脑；每次操作后重新 capture 核对实际效果。用户可随时接管。',
    'inputSchema':{'type':'object','properties':{'resource_id':{'type':'string'},
        'action':{'type':'string','enum':['status','list_apps','list_windows','capture']},'app':{'type':'string'},
        'window_id':{'type':'integer','minimum':0},'pid':{'type':'integer','minimum':1}},
        'required':['resource_id','action'],'additionalProperties':False}},
    {'name':'wearing_computer_request_input','description':'先 capture 取得新 frame_id，再执行电脑操作。用户可一次授权本轮任务，随后同一应用的普通动作会连续执行并返回实际回执，不要逐次询问。普通浏览、填写、滚动声明 checkpoint=routine；发送消息、付款下单、删除、账号安全变更、接受新协议必须声明 commitment，停下来取得确认。操作后重新观察核对；结果不明时不重试。',
     'inputSchema':{'type':'object','properties':{'resource_id':{'type':'string'},'action':DesktopAction.model_json_schema(),
        'reason':{'type':'string','minLength':2,'maxLength':500},'checkpoint':{'type':'string','enum':['routine','commitment'],'default':'commitment'}},'required':['resource_id','action','reason','checkpoint'],'additionalProperties':False}},
    {'name':'wearing_computer_input_result','description':'读取这次电脑操作的用户决定与实际回执，不会重复动作；完成后重新 capture 核对。',
     'inputSchema':{'type':'object','properties':{'resource_id':{'type':'string'},'approval_id':{'type':'string'}},
        'required':['resource_id','approval_id'],'additionalProperties':False}}]
