import sublime
import os
import sys
import json
import csv
import urllib
import pprint
import sys
import re
import time
import datetime
import base64
import zipfile
import shutil
import webbrowser
import xml.dom.minidom

from .salesforce.lib import xmlformatter
from .salesforce import message
from .salesforce import xmltodict
from .salesforce.lib import dateutil
from .salesforce.lib.dateutil import tz
from .salesforce.lib.panel import Printer
from . import context
from xml.sax.saxutils import unescape


def get_session_info(settings):
    """ Get Session Info

    Arguments:

    * settings -- plugin settings

    Return:

    * session -- Session Info
    """

    session = None
    session_directory = os.path.join(settings["workspace"], ".config", "session.json")
    if os.path.isfile(session_directory):
        session = json.loads(open(session_directory).read())

    return session

def get_local_timezone_offset():
    """ Return the timezone offset of local time with GMT standard

    Return:

    * offset_hours -- date time offset hours with GMT
    """

    localtz = dateutil.tz.tzlocal()
    localoffset = localtz.utcoffset(datetime.datetime.now(localtz))
    offset_hours = localoffset.total_seconds() / 3600

    return offset_hours

# https://docs.python.org/3.2/library/datetime.html#strftime-and-strptime-behavior
# http://stackoverflow.com/questions/12015170/how-do-i-automatically-get-the-timezone-offset-for-my-local-time-zone
def local_datetime(server_datetime_str):
    """ Convert the Datetime got from server to local GMT Datetime

    Return:

    * local_datetime -- local datetime with GMT offset
    """
    
    offset = get_local_timezone_offset()
    local_datetime = datetime.datetime.strptime(server_datetime_str[:19], '%Y-%m-%dT%H:%M:%S')
    local_datetime += datetime.timedelta(hours=offset)

    return local_datetime

def server_datetime(local_datetime):
    """ Convert the Datetime got from local to GMT Standard

    Return:

    * server_datetime -- standard GMT server datetime
    """

    offset = get_local_timezone_offset()
    server_datetime = local_datetime + datetime.timedelta(hours=-offset)

    return server_datetime

def populate_all_components():
    """ Get all components from local cache
    """

    # Get username
    settings = context.get_settings()
    username = settings["username"]

    # If sobjects is exist in local cache, just return it
    component_metadata = sublime.load_settings("component_metadata.sublime-settings")
    if not component_metadata.has(username):
        Printer.get('error').write("No Cache, Please New Project Firstly.")
        return {}

    return_component_attributes = {}
    for component_type in component_metadata.get(username).keys():
        component_attributes = component_metadata.get(username)[component_type]
        for key in component_attributes.keys():
            component_id = component_attributes[key]["id"]
            component_type = component_attributes[key]["type"]
            component_name = component_attributes[key]["name"]
            return_component_attributes[component_type+"."+component_name] = component_id

    return return_component_attributes

def populate_components(_type):
    """
    Get dict (Class Name => Class Id) which NamespacePrefix is null in whole org

    @return: {
        classname: classid
        ...
    }
    """
    # Get username
    settings = context.get_settings()
    username = settings["username"]

    # If sobjects is exist in local cache, just return it
    component_metadata = sublime.load_settings("component_metadata.sublime-settings")
    if not component_metadata.has(username):
        Printer.get("error").write("No cache, please create new project firstly")
        return {}

    return component_metadata.get(username).get(_type)

def populate_lighting_applications():
    settings = context.get_settings()
    workspace = settings["workspace"]
    username = settings["username"]
    aura_path = os.path.join(workspace, "src", "aura")
    component_settings = sublime.load_settings("component_metadata.sublime-settings")
    if not component_settings.has(username):
        return {}

    aura_attributes = {}
    aura_cache = component_settings.get(username).get("AuraDefinitionBundle")
    for name in aura_cache:
        aura_name, element_name = aura_cache[name]["name"].split("/")
        if element_name.endswith(".app"):
            aura_attributes[aura_name] = aura_cache[name]

    return aura_attributes

def populate_sobjects_describe():
    """
    Get the sobjects list in org.
    """

    # Get username
    settings = context.get_settings()
    username = settings["username"]

    # If sobjects is exist in sobjects_completion.sublime-settings, just return it
    sobjects_completions = sublime.load_settings("sobjects_completion.sublime-settings")
    if not sobjects_completions.has(username):
        Printer.get('error').write("No Cache, Please New Project Firstly.")
        return

    sobjects_describe = {}
    sd = sobjects_completions.get(username)["sobjects"]
    for key in sd:
        sobject_describe = sd[key]
        sobjects_describe[sobject_describe["name"]] = sobject_describe
    return sobjects_describe

def populate_all_test_classes():
    # Get username
    settings = context.get_settings()
    username = settings["username"]

    component_metadata = sublime.load_settings("component_metadata.sublime-settings")
    if not component_metadata.has(username):
        Printer.get('error').write("No cache, please create new project firstly.")
        return

    classes = component_metadata.get(username)["ApexClass"]
    test_class_ids = []
    for class_name, class_attr in classes.items():
        if not class_attr["is_test"]: continue
        test_class_ids.append(class_attr["id"])

    return test_class_ids
    
def get_sobject_caches(setting_name):
    """ Return the specified local cache of default project

    Return:

    * caches -- sobject local cache in default project
    """
    config_settings = context.get_settings()
    projects = config_settings["projects"]
    settings = sublime.load_settings(setting_name)

    caches = []
    for p in projects:
        if settings.has(projects[p]["username"]):
            caches.append([p, projects[p]["username"]])

    return caches

def clear_cache(username, setting_name):
    """ Clear the specified local cache of default project

    Arguments:

    * username -- the login username of default project
    """
    settings = sublime.load_settings(setting_name)
    settings = settings.erase(username)
    sublime.save_settings(setting_name)
    sublime.status_message(username + " cache is cleared")

def get_sobject_metadata_and_symbol_tables(username):
    """ Return the sobject cache of default project

    Arguments:
    * username -- username of current default project

    Returns:
    * sobject metadata -- the sobject metadata of default project
    """
    sobjects_metadata = {}
    symbol_tables = {}

    sobjects_settings = sublime.load_settings("sobjects_completion.sublime-settings")
    symbol_tables_settings = sublime.load_settings("symbol_table.sublime-settings")
    if sobjects_settings.has(username):
        sobjects_metadata = sobjects_settings.get(username)

    if symbol_tables_settings.has(username):
        symbol_tables = symbol_tables_settings.get(username)

    return sobjects_metadata, symbol_tables

def get_sobject_completion_list(sobject_describe, prefix="", display_child_relationships=True):
    """ Return the formatted completion list of sobject

    Arguments:

    * sobject_describe  -- describe result of sobject
    * prefix            -- optional; sometimes, parent relationshipName may refer to multiple sobject,
                           so we need to add the prefix to distinct different completions
    * display_child_relationships -- optional; indicate whether display sobject child relationship names
    """
    # Fields Describe
    completion_list = []
    fields = sobject_describe["fields"]
    for field_name_desc in sorted(fields):
        field_name = fields[field_name_desc]
        completion = ("%s%s" % (prefix, field_name_desc), field_name)
        completion_list.append(completion)

    # Parent Relationship Describe
    for key in sorted(sobject_describe["parentRelationships"]):
        parent_sobject = sobject_describe["parentRelationships"][key]
        completion_list.append((prefix + key + "\t" + parent_sobject + "(c2p)", key)) 

    # Child Relationship Describe
    if display_child_relationships:
        for key in sorted(sobject_describe["childRelationships"]):
            child_sobject = sobject_describe["childRelationships"][key]
            completion_list.append((prefix + key + "\t" + child_sobject + "(p2c)", key))

    return completion_list

def get_component_completion(username, component_type):
    """ Return the formatted completion list of component

    Return:
    * completion_list -- all apex component completion list
    """

    completion_list = []
    component_settings = sublime.load_settings(context.COMPONENT_METADATA_SETTINGS)
    if component_settings.has(username):
        component_attrs = component_settings.get(username)
        if component_type in component_attrs:
            components = component_attrs[component_type]
            for name in components:
                if "name" not in components[name]: continue
                component_name = components[name]["name"]
                if component_type == "ApexComponent":
                    completion_list.append(("c:"+component_name+"\t"+component_type, "c:"+component_name))
                else:
                    completion_list.append((component_name+"\t"+component_type, component_name))
    
    return completion_list

def get_component_attribute_completion(settings, component_name):
    workspace = settings["workspace"]+""

def convert_15_to_18(the15Id):
    """ Convert Salesforce 15 Id to 18 Id

    Arguments:

    * the15Id - to be converted 15 Id

    Return:

    * 18 Id - converted 18 Id
    """
    
    if not the15Id or len(the15Id) != 15: return the15Id

    cmap = {
        "00000": "A", "00001": "B", "00010": "C", "00011": "D", "00100": "E",
        "00101": "F", "00110": "G", "00111": "H", "01000": "I", "01001": "J",
        "01010": "K", "01011": "L", "01100": "M", "01101": "N", "01110": "O", 
        "01111": "P", "10000": "Q", "10001": "R", "10010": "S", "10011": "T", 
        "10100": "U", "10101": "V", "10110": "W", "10111": "X", "11000": "Y", 
        "11001": "Z", "11010": "0", "11011": "1", "11100": "2", "11101": "3", 
        "11110": "4", "11111": "5"
    }

    chars = [cmap["".join(["1" if c.isupper() else "0" for c in char[::-1]])] \
        for char in list(chunks(the15Id, 5))]

    return the15Id + "".join(chars)

def chunks(l, n):
    """ Yield successive n-sized chunks from l.

    Arguments:

    * l - to be chunked list
    * n - split size
    """
    for i in range(0, len(l), n):
        yield l[i:i+n]

    return list(l)

def open_with_browser(show_url, use_default_chrome=True):
    """ Utility for open file in browser

    Arguments:

    * use_default_browser -- optional; if true, use chrome configed in settings to open it
    """

    settings = context.get_settings()
    browser_path = settings["default_chrome_path"]
    if not use_default_chrome or not os.path.exists(browser_path):
        webbrowser.open_new_tab(show_url)
    else:
        webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(browser_path))
        webbrowser.get('chrome').open_new_tab(show_url)

def advance_to_first_non_white_space_on_line(view, pt):
    while True:
        c = view.substr(pt)
        if c == " " or c == "\t":
            pt += 1
        else:
            break

    return pt

def has_non_white_space_on_line(view, pt):
    while True:
        c = view.substr(pt)
        if c == " " or c == "\t":
            pt += 1
        else:
            return c != "\n"

def build_comment_data(view, pt):
    shell_vars = view.meta_info("shellVariables", pt)
    if not shell_vars:
        return ([], [])

    # transform the list of dicts into a single dict
    all_vars = {}
    for v in shell_vars:
        if 'name' in v and 'value' in v:
            all_vars[v['name']] = v['value']

    line_comments = []
    block_comments = []

    # transform the dict into a single array of valid comments
    suffixes = [""] + ["_" + str(i) for i in range(1, 10)]
    for suffix in suffixes:
        start = all_vars.setdefault("TM_COMMENT_START" + suffix)
        end = all_vars.setdefault("TM_COMMENT_END" + suffix)
        mode = all_vars.setdefault("TM_COMMENT_MODE" + suffix)
        disable_indent = all_vars.setdefault("TM_COMMENT_DISABLE_INDENT" + suffix)

        if start and end:
            block_comments.append((start, end, disable_indent == 'yes'))
            block_comments.append((start.strip(), end.strip(), disable_indent == 'yes'))
        elif start:
            line_comments.append((start, disable_indent == 'yes'))
            line_comments.append((start.strip(), disable_indent == 'yes'))

    return (line_comments, block_comments)

def is_entirely_line_commented(view, comment_data, region):
    (line_comments, block_comments) = comment_data

    start_positions = [advance_to_first_non_white_space_on_line(view, r.begin())
        for r in view.lines(region)]

    start_positions = list(filter(lambda p: has_non_white_space_on_line(view, p),
        start_positions))

    if len(start_positions) == 0:
        return False

    for pos in start_positions:
        found_line_comment = False
        for c in line_comments:
            (start, disable_indent) = c
            comment_region = sublime.Region(pos,
                pos + len(start))
            if view.substr(comment_region) == start:
                found_line_comment = True
        if not found_line_comment:
            return False

    return True

def get_variable_type(view, pt, pattern):
    """Return the matched soql region

    Arguments:

    * view -- current active view
    * pt - the cursor point
    * pattern - the regular expression for finding matched region
    """
    # Get the matched variable type
    matched_regions = view.find_all(pattern, sublime.IGNORECASE)
    variable_type = ""

    comment_data = build_comment_data(view, pt)
    match_region = None
    for match_region in matched_regions:
        # Skip comment line
        match_str = view.substr(match_region)
        is_comment = is_entirely_line_commented(view, comment_data, match_region)
        if not is_comment: break

    if not match_region: return ""
    matched_block = view.substr(match_region).strip()
    
    # If list, map, set
    if "<" in matched_block and ">" in matched_block:
        variable_type = matched_block.split("<")[0].strip()
    # String[] strs;
    elif "[]" in matched_block:
        variable_type = 'list'
    # String str;
    else:
        variable_type = matched_block.split(" ")[0]

    return variable_type

def get_soql_match_region(view, pt):
    """Return the matched soql region

    Arguments:

    * view -- current Active View

    Return:

    * matched_region -- Found SOQL
    * sobject_name -- Found Sobject Name in SOQL
    * is_between_start_and_from -- the cursor point is between start and the last from
    """
    pattern = "SELECT\\s+[\\w\\n,.:_\\s()]*\\s+FROM\\s+\\w+"
    matched_regions = view.find_all(pattern, sublime.IGNORECASE)
    matched_region = None
    is_between_start_and_from = False
    sobject_name = None
    for m in matched_regions:
        if m.contains(pt):
            matched_region = m
            break

    if not matched_region: 
        return (matched_region, is_between_start_and_from, sobject_name)

    match_str = view.substr(matched_region)
    match_begin = matched_region.begin()
    select_pos = match_str.lower().find("select")
    from_pos = match_str.lower().rfind("from")

    if pt >= (select_pos + match_begin) and pt <= (from_pos + match_begin):
        is_between_start_and_from = True
        sobject_name = match_str[from_pos+5:]
        sobject_name = sobject_name.strip()

    return (matched_region, is_between_start_and_from, sobject_name)

def parse_symbol_table(symbol_table):
    """Parse the symbol_table to completion (Copied From MavensMate)

    Arguments:

    * symbol_table -- ApexClass Symbol Table
    """
    completions = {}
    if not symbol_table: return completions;
    if 'constructors' in symbol_table:
        for c in symbol_table['constructors']:
            params = []
            visibility = c["visibility"].capitalize() if "visibility" in c else "Public"

            if 'parameters' in c and type(c['parameters']) is list and len(c['parameters']) > 0:
                for p in c['parameters']:
                    params.append(p["type"].capitalize() + " " + p["name"])
                paramStrings = []
                for i, p in enumerate(params):
                    paramStrings.append("${"+str(i+1)+":"+params[i]+"}")
                paramString = ", ".join(paramStrings)
                completions[visibility+" "+c["name"]+"("+", ".join(params)+")"] =\
                    c["name"]+"("+paramString+")"
            else:
                completions[visibility+" "+c["name"]+"()"] = c["name"]+"()${1:}"

    if 'properties' in symbol_table:
        for c in symbol_table['properties']:
            visibility = c["visibility"].capitalize() if "visibility" in c else "Public"
            property_type = c["type"].capitalize() if "type" in c and c["type"] else ""
            completions[visibility+" "+c["name"]+"\t"+property_type] = c["name"]

    if 'methods' in symbol_table:
        for c in symbol_table['methods']:
            params = []
            visibility = c["visibility"].capitalize() if "visibility" in c else "Public"
            if 'parameters' in c and type(c['parameters']) is list and len(c['parameters']) > 0:
                for p in c['parameters']:
                    params.append(p["type"]+" "+p["name"])
            if len(params) == 1:
                completions[visibility+" "+c["name"]+"("+", ".join(params)+") \t"+c['returnType']] =\
                    c["name"]+"(${1:"+", ".join(params)+"})"
            elif len(params) > 1:
                paramStrings = []
                for i, p in enumerate(params):
                    paramStrings.append("${"+str(i+1)+":"+params[i]+"}")
                paramString = ", ".join(paramStrings)
                completions[visibility+" "+c["name"]+"("+", ".join(params)+") \t"+c['returnType']] =\
                    c["name"]+"("+paramString+")"
            else:
                completions[visibility+" "+c["name"]+"("+", ".join(params)+") \t"+c['returnType']] =\
                    c["name"]+"()${1:}"

    if 'innerClasses' in symbol_table:
        for c in symbol_table["innerClasses"]:
            if 'constructors' in c and len(c['constructors']) > 0:
                for con in c['constructors']:
                    visibility = con["visibility"].capitalize() if "visibility" in con else "Public"
                    params = []
                    if 'parameters' in con and type(con['parameters']) is list and len(con['parameters']) > 0:
                        for p in con['parameters']:
                            params.append(p["type"].capitalize()+" "+p["name"])
                        paramStrings = []
                        for i, p in enumerate(params):
                            paramStrings.append("${"+str(i+1)+":"+params[i]+"}")
                        paramString = ", ".join(paramStrings)
                        completions[visibility+" "+con["name"]+"("+", ".join(params)+")"] =\
                            c["name"]+"("+paramString+")"
                    else:
                        completions[visibility+" "+con["name"]+"()"] =\
                            c["name"]+"()${1:}"
            else:
                completions["Inner Class "+c["name"]+"\t"+"Inner Class"] = c["name"]+"$1"

    return completions

def add_operation_history(operation, history_content):
    """Keep the history in the local history

    Arguments:

    * operation -- the operation source
    * history_content -- the content needed to keep
    """
    settings = context.get_settings()
    if not settings["keep_operation_history"]: return

    splits = operation.split("/")
    if len(splits) == 1:
        folder, operation = "", splits[0]
    elif len(splits) == 2:
        folder, operation = splits
    outputdir = settings["workspace"] + "/.history/" + folder
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    time_stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    history = "%s\n```java\n%s\n```\n\n" % (time_stamp, history_content)
    fp = open(outputdir + "/%s.md" % operation, "ab")
    fp.write(history.encode("utf-8"))
    fp.close()

def add_config_history(operation, content, ext="json"):
    """Keep the history in the local history

    Arguments:

    * operation -- the operation source
    * history_content -- the content needed to keep
    """
    settings = context.get_settings()
    outputdir = settings["workspace"]+"/.config"
    if not os.path.exists(outputdir): 
        os.makedirs(outputdir)

    fp = open(outputdir + "/%s.%s" % (operation, ext), "w")
    fp.write(json.dumps(content, indent=4))
    fp.close()

    # After write the file to local, refresh sidebar
    sublime.active_window().run_command("refresh_folder_list")

def export_report_api(rootdir):
    reports = []
    for parent,dirnames,filenames in os.walk(rootdir):
        for filename in filenames:
            if not filename.endswith(".report"): continue
            report_dir = parent + "/" + filename
            report_folder = os.path.split(parent)[1]
            report_name = filename.split(".")[0]
            report_api = util.getUniqueElementValueFromXmlString(open(report_dir, "rb").read(), "name")

            report_dict[report_api] = report_name
            reports.append({"name": report_name, "api": report_api, "folder": report_folder})

    util.list2csv(rootdir + "/test.csv", reports)

def check_new_component_enabled():
    """If project in current date is not created, new component is not enabled

    Returns:

    * * -- whether project in current date is exist
    """
    settings = context.get_settings()
    return os.path.exists(settings["workspace"])
    
def check_workspace_available(settings=None):
    """Check workspace is available, if not make it

    Arguments:

    * settings -- settings of this plugin
    """
    if not settings: settings = context.get_settings()
    if not os.path.exists(settings["workspace"]):
        sublime.active_window().run_command('create_new_project', {
            "switch_project": False
        })

def get_view_by_name(view_name):
    """Get view by view name

    Arguments:

    * view_name -- name of view in sublime

    Returns:

    * view -- sublime open tab
    """
    view = None
    for v in sublime.active_window().views():
        if not v.name(): continue
        if v.name() == view_name:
            view = v

    return view

def get_view_by_file_name(file_name):
    """
    Get the view in the active window by the view_name

    Arguments:

    * view_id: view name

    Returns:

    * return: view
    """

    view = None
    for v in sublime.active_window().views():
        if not v.file_name(): continue
        if file_name in v.file_name():
            view = v

    return view

def get_view_by_id(view_id):
    """
    Get the view in the active window by the view_id

    * view_id: id of view
    * return: view
    """

    view = None
    for v in sublime.active_window().views():
        if not v.id(): continue
        if v.id() == view_id:
            view = v

    return view

def build_package_types(package_xml_content):
    result = xmltodict.parse(package_xml_content)

    elements = []
    metadata_types = result["Package"]["types"]

    # If there is only one types in package
    if isinstance(metadata_types, dict): 
        metadata_types = [metadata_types]

    types = {}
    for t in metadata_types:
        name = t["name"]
        members = t["members"]

        if isinstance(members, str):
            types[name] = [members]
        elif isinstance(members, list):
            types[name] = members

    return types

def build_folder_types(dirs):
    """  Build folders_dict for folder refreshing
        {
            "ApexClass": ["*"],
            "ApexTrigger": ["*"],
            "CustomObject": ["*"]
        }
    """
    settings = context.get_settings()
    dname = settings["default_project_name"]
    types = {}
    for _dir in dirs:
        base, folder = os.path.split(_dir)
        
        if folder not in settings: continue
        if dname not in _dir: continue

        xml_name = settings[folder]["xmlName"]
        types[xml_name] = make_types(settings, xml_name)

    return types

def make_types(settings, xml_name):
    if xml_name == "CustomObject":
        sobjects = [
            "Account", "AccountContactRole", "Activity", "Asset", 
            "Campaign", "CampaignMember", "Case", "CaseComment", 
            "CaseContactRole", "Contact", "ContentVersion", "Contract", 
            "ContractContactRole", "Event", "ForecastingQuota", "Idea", 
            "Lead", "Opportunity", "OpportunityCompetitor", "OpportunityContactRole", 
            "OpportunityLineItem", "OpportunityTeamMember", "PartnerRole", 
            "Pricebook2", "PricebookEntry", "Product2", 
            "Quote", "QuoteLineItem", "Site", "Solution", "Task", "User"
        ]
        sobjects.append("*")
        return sobjects
    else:
        return ["*"]

def build_package_dict(files, ignore_folder=True):
    """ Build Package Dict as follow structure by files
        {
            'ApexClass': [{
                'dir': <file path>,
                'folder': 'classes',
                'name': 'AccountController',
                'extension': '.cls'
            }],
            'ApexComponent': [{
                'dir': <file path>,
                'folder': 'components',
                'name': 'SiteFooter',
                'extension': '.component'
            }]
        }
    """
    settings = context.get_settings()
    package_dict = {}
    for f in files:
        # Ignore folder
        if ignore_folder and not os.path.isfile(f): continue

        # Ignore "-meta.xml"
        if f.endswith("-meta.xml"): continue

        # Get xml_name and code name
        if ignore_folder:
            base, name = os.path.split(f)
            name, extension = name.split(".")
            base, folder = os.path.split(base)
            xml_name = settings[folder]["xmlName"]
            file_dict = {
                "name": name,
                "dir": f,
                "folder": folder,
                "extension": "."+extension
            }
        else:
            base, name = os.path.split(f)
            base, folder = os.path.split(base)
            xml_name = settings[folder]["xmlName"]
            file_dict = {
                "name": name,
                "dir": f,
                "folder": folder,
                "extension": ""
            }

        # Build dict
        if xml_name in package_dict:
            package_dict[xml_name].append(file_dict)
        else:
            package_dict[xml_name] = [file_dict]

    return package_dict

def build_package_xml(settings, package_dict):
    """ Build Package XML as follow structure
        <?xml version="1.0" encoding="UTF-8"?>
        <Package xmlns="http://soap.sforce.com/2006/04/metadata">
            <types>
                <met:members>*</met:members>
                <met:members>Account</met:members>
                <name>CustomObject</name>
            </types>
            <version>32.0</version>
        </Package>
    """

    # Build types for package.xml
    types = []
    for meta_type in package_dict:
        members = []
        for f in package_dict[meta_type]:
            members.append("<members>%s</members>" % f["name"])

        types.append("""
        <types>
            %s
            <name>%s</name>
        </types>
        """ % (" ".join(members), meta_type))

    # Build package.xml
    package_xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <Package xmlns="http://soap.sforce.com/2006/04/metadata">
            %s
            <version>%s.0</version>
        </Package>
    """ % (" ".join(types), settings["api_version"])

    return package_xml_content

def build_destructive_package(files, ignore_folder=True):
    settings = context.get_settings()
    workspace = settings["workspace"]
    if not os.path.exists(workspace): 
        os.makedirs(workspace)

    # Constucture package dict 
    package_dict = build_package_dict(files, ignore_folder)

    # Build destructiveChanges.xml
    destructive_xml_content = build_package_xml(settings, package_dict)
    destructive_xml_path = workspace+"/destructiveChanges.xml"
    open(destructive_xml_path, "wb").write(destructive_xml_content.encode("utf-8"))

    # Build package.xml
    package_xml_content = build_package_xml(settings, {})
    package_xml_path = workspace+"/package.xml"
    open(package_xml_path, "wb").write(package_xml_content.encode("utf-8"))

    # Create temp zipFile
    zipfile_path = workspace + "/test.zip"
    zf = zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED)

    # Compress destructive_xml and package_xml into temp zipFile
    # After that, close the input stream
    zf.write(package_xml_path, "package.xml")
    zf.write(destructive_xml_path, "destructiveChanges.xml")
    zf.close()

    # Remove temp files
    os.remove(package_xml_path)
    os.remove(destructive_xml_path)

    # base64 encode zip package
    base64_package = base64_encode(zipfile_path)

    # Remove temporary `test.zip`
    os.remove(zipfile_path)

    return base64_package

def build_deploy_package(files):
    # Initiate zipfile
    settings = context.get_settings()
    if not os.path.exists(settings["workspace"]):
        os.makedirs(settings["workspace"])

    zipfile_path = settings["workspace"] + "/test.zip"
    zf = zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED)

    # Get package dict
    package_dict = build_package_dict(files)

    # Add files to zip
    for meta_type in package_dict:
        for f in package_dict[meta_type]:
            zf.write(f["dir"], "%s/%s%s" % (f["folder"], f["name"], f["extension"]))

            # If -meta.xml is exist, add it to folder
            met_xml = f["dir"] + "-meta.xml"
            if os.path.isfile(met_xml):
                zf.write(met_xml, "%s/%s%s" % (f["folder"], f["name"], f["extension"]+"-meta.xml"))

    # Prepare package XML content
    package_xml_content = build_package_xml(settings, package_dict)
    package_xml_content = format_xml(package_xml_content)

    # Write package content to .package path
    package_xml_dir = settings["workspace"]+"/.deploy"
    if not os.path.exists(package_xml_dir): os.makedirs(package_xml_dir)
    time_stamp = time.strftime("%Y%m%d%H%M", time.localtime(time.time()))
    package_xml_dir = package_xml_dir + "/package-%s.xml" % time_stamp
    open(package_xml_dir, "wb").write(package_xml_content)
    zf.write(package_xml_dir, "package.xml")

    # Close zip input stream
    zf.close()

    # base64 encode zip package
    base64_package = base64_encode(zipfile_path)

    # Remove temporary `test.zip`
    os.remove(zipfile_path)

    return base64_package

def compress_resource_folder(resource_folder):
    """ Prepare base64 encoded zip for uploading static resource

    Arguments:

    * resource_folder - static resource folder in project
    """

    static_resource_path, resource_name = os.path.split(resource_folder)

    # Create StaticResource File
    static_resource_file = os.path.join(static_resource_path, resource_name+".resource")
    zf = zipfile.ZipFile(static_resource_file, "w", zipfile.ZIP_DEFLATED)
    for dirpath, dirnames, filenames in os.walk(resource_folder):
        basename = dirpath[len(resource_folder)+1:]
        for filename in filenames:
            zf.write(os.path.join(dirpath, filename), basename+"/"+filename)
    zf.close()

    # Build package
    base64_package = build_deploy_package([static_resource_file])

    return base64_package

def build_aura_package(files_or_dirs):
    # Build package
    settings = context.get_settings()
    workspace = settings["workspace"]
    if not os.path.exists(workspace): os.makedirs(workspace)
    zipfile_path = workspace+"/aura.zip"
    zf = zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED)

    aura_names = []
    for _file_or_dir in files_or_dirs:
        if os.path.isfile(_file_or_dir):
            base, aura_element = os.path.split(_file_or_dir)
            base, aura_name = os.path.split(base)
            base, meta_type = os.path.split(base)
            aura_names.append(aura_name)
            zf.write(_file_or_dir, "%s/%s/%s" % (meta_type, aura_name, aura_element))
        else:
            base, aura_name = os.path.split(_file_or_dir)
            base, meta_type = os.path.split(base)
            aura_names.append(aura_name)
            for dirpath, dirnames, filenames in os.walk(_file_or_dir):
                base, aura_name = os.path.split(dirpath)
                if not filenames:
                    zf.write(dirpath, meta_type+"/"+aura_name)
                else:
                    for filename in filenames:
                        zf.write(os.path.join(dirpath, filename), "%s/%s/%s" % (meta_type, aura_name, filename))

    # Write package.xml to zip
    package_xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <Package xmlns="http://soap.sforce.com/2006/04/metadata">
            <types>
                %s
                <name>AuraDefinitionBundle</name>
            </types>
            <version>%s.0</version>
        </Package>
    """ % ("\n".join(["<members>%s</members>" % a for a in aura_names]), settings["api_version"])
    package_xml_path = settings["workspace"]+"/package.xml"
    open(package_xml_path, "wb").write(package_xml_content.encode("utf-8"))
    zf.write(package_xml_path, "package.xml")
    os.remove(package_xml_path)

    # Close zip input stream
    zf.close()

    # base64 encode zip package
    base64_package = base64_encode(zipfile_path)

    # Remove temporary `test.zip`
    os.remove(zipfile_path)

    return base64_package

def base64_encode(zipfile):
    with open(zipfile, "rb") as f:
        bytes = f.read()
        base64String = base64.b64encode(bytes)

    return base64String.decode('UTF-8')

def compress_package(package_dir):
    zipfile_path = package_dir+"/archive.zip"
    zf = zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED)
    for dirpath, dirnames, filenames in os.walk(package_dir):
        basename = dirpath[len(package_dir)+1:]
        for filename in filenames:
            zf.write(os.path.join(dirpath, filename), basename+"/"+filename) 
    zf.close()

    base64_package = base64_encode(zipfile_path)
    os.remove(zipfile_path)

    return base64_package

def extract_encoded_zipfile(encoded_zip_file, extract_to, ignore_package_xml=False):
    """ Decode the base64 encoded file and 
        extract the zip file to workspace and 
        rename the "unpackaged" to "src"
    """

    if not os.path.exists(extract_to):
        os.makedirs(extract_to)

    zipfile_path = os.path.join(extract_to, "package.zip")
    with open(zipfile_path, "wb") as fout:
        fout.write(base64.b64decode(encoded_zip_file))
        fout.close()

    extract_file(zipfile_path, extract_to, ignore_package_xml)

    # Remove original src tree
    os.remove(zipfile_path)

    # In windows, folder is not shown in the sidebar, 
    # we need to refresh the sublime workspace to show it
    sublime.active_window().run_command("refresh_folder_list")

def extract_zipfile(zipfile_path, extract_to):
    """ Extract Zip File to current folder
    """

    try:
        zfile = zipfile.ZipFile(zipfile_path, 'r')
    except zipfile.BadZipFile as ex:
        Printer.get('error').write(str(ex))
        return

    if not os.path.exists(extract_to): 
        os.makedirs(extract_to)

    for filename in zfile.namelist():
        if filename.endswith('/'): continue
        f = os.path.join(extract_to, "", filename)

        if not os.path.exists(os.path.dirname(f)):
            os.makedirs(os.path.dirname(f))

        with open(f, "wb") as fp:
            fp.write(zfile.read(filename))

    zfile.close()

def extract_file(zipfile_path, extract_to, ignore_package_xml=False):
    zfile = zipfile.ZipFile(zipfile_path, 'r')
    for filename in zfile.namelist():
        if filename.endswith('/'): continue
        if ignore_package_xml and filename == "unpackaged/package.xml": continue
        if filename.startswith("unpackaged"):
            f = os.path.join(extract_to, filename.replace("unpackaged", "src"))
        else:
            f = os.path.join(extract_to, "packages", filename)

        if not os.path.exists(os.path.dirname(f)):
            os.makedirs(os.path.dirname(f))

        with open(f, "wb") as fp:
            fp.write(zfile.read(filename))

    zfile.close()

def extract_zip(base64String, extract_to):
    """
    1. Decode base64String to zip
    2. Extract zip to files
    """

    # Decode base64String to zip
    if not os.path.exists(extract_to): os.makedirs(extract_to)
    zipfile_path = extract_to + "/package.zip"
    with open(zipfile_path, "wb") as fout:
        fout.write(base64.b64decode(base64String))

    # Extract file to target path
    extract_file(zipfile_path, extract_to)

    # Remove package.zip
    os.remove(zipfile_path)

    return zipfile_path

def parse_package(package_content):
    """Parse package types to specified format

    Arguments:

    * package_path -- package content to parse

    Convert
    ```
    <?xml version="1.0" encoding="UTF-8"?>
    <Package xmlns="http://soap.sforce.com/2006/04/metadata">
        <types>
            <members>*</members>
            <name>ApexClass</name>
        </types>
        <version>32.0</version>
    </Package>
    ```

    To
    ```
    <types>
        <met:members>*</met:members>
        <name>ApexClass</name>
    </types>
    ```

    """
    result = xmltodict.parse(package_content)

    elements = []
    types = result["Package"]["types"]

    # If there is only one types in package
    if isinstance(types, dict): types = [types]

    for t in types:
        members = []
        if "members" in t and isinstance(t["members"], list):
            for member in t["members"]:
                members.append("<met:members>%s</met:members>" % member)
        else:
            members.append("<met:members>%s</met:members>" % t["members"])

        elements.append("<types>%s%s</types>" % (
            "".join(members), 
            "<name>%s</name>" % t["name"]
        ))

    return "".join(elements) + "<met:version>%s</met:version>" % result["Package"]["version"]

def reload_apex_code_cache(file_properties, settings=None):
    # Get settings
    if not settings: settings = context.get_settings()

    component_body_or_markup = {
        "ApexClass": "Body",
        "ApexTrigger": "Body",
        "StaticResource": "Body",
        "ApexPage": "Markup",
        "ApexComponent": "Markup",
        "AuraDefinitionBundle": ""
    }

    # If the package only contains `package.xml`
    if isinstance(file_properties, dict): file_properties = [file_properties]
    component_attrs = {}
    # print (json.dumps(file_properties))
    for filep in file_properties:
        # No need to process package.xml
        if filep["type"] not in component_body_or_markup: continue

        # Get component type
        component_type = filep["type"]

        if component_type in component_attrs:
            component_attr = component_attrs[component_type]
        else:
            component_attr = {}

        component_name = filep['fullName']
        component_id = filep["id"]
        namespacePrefix = filep["namespacePrefix"] if "namespacePrefix" in filep else ""
        component_url = "/services/data/v%s.0/sobjects/%s/%s" % (
            settings["api_version"], component_type, component_id
        )

        component_attr[component_name.lower()] = {
            "namespacePrefix": namespacePrefix,
            "name": component_name,
            "body": component_body_or_markup[component_type],
            "extension": "."+(filep["fileName"].split(".")[1]),
            "type": component_type,
            "url": component_url,
            "id": component_id
        }

        # Check whether component is Test Class or not
        if component_type == "ApexClass":
            cl = component_name.lower()
            component_attr[component_name.lower()]["is_test"] =\
                cl.startswith("test") or cl.endswith("test")

        component_attrs[component_type] = component_attr

    component_settings = sublime.load_settings(context.COMPONENT_METADATA_SETTINGS)
    component_attributes = component_settings.get(settings["username"])
    if not component_attributes: component_attributes = {}
    for component_type in component_attrs:
        component_attributes[component_type] = component_attrs[component_type]
    component_settings.set(settings["username"], component_attributes)
    sublime.save_settings(context.COMPONENT_METADATA_SETTINGS)

def format_debug_logs(settings, records):
    if len(records) == 0: return "No available logs."

    # Used to list debug logs as below format
    debug_log_headers = [
        "Id", "StartTime", "DurationMilliseconds", "Status", "LogLength", "Operation"
    ]
    debug_log_headers_properties = {
        "Id": {
            "width": 20,
            "label": "Log Id"
        },
        "StartTime": {
            "width": 22,
            "label": "Start Time"
        },
        "Request": {
            "width": 13,
            "label": "Request Type"
        },
        "Application": {
            "width": 12,
            "label": "Application"
        },
        "Status": {
            "width": 10,
            "label": "Status"
        },
        "LogLength": {
            "width": 8,
            "label": "Size(b)"
        },
        "DurationMilliseconds": {
            "width": 13,
            "label": "Duration(ms)"
        },
        "Operation": {
            "width": 50,
            "label": "Operation"
        }
    }

    # Headers
    headers = ""
    for header in debug_log_headers:
        headers += "%-*s" % (debug_log_headers_properties[header]["width"], 
            debug_log_headers_properties[header]["label"])

    # Content
    content = ""
    records = sorted(records, key=lambda k : k['StartTime'])
    for record in records:
        for header in debug_log_headers:
            if header == "StartTime":
                content += "%-*s" % (debug_log_headers_properties[header]["width"],
                    local_datetime(record[header]))
                continue
            content += "%-*s" % (debug_log_headers_properties[header]["width"], record[header])
        content += "\n"

    return "\n" + headers + "\n" + (len(headers) * "-") + "\n" + content[:len(content)-1]

def format_error_message(result):
    """Format message as below format
           message:     The requested resource does not exist   
               url:     url
         errorCode:     NOT_FOUND                       
       status_code:     404     

    * result -- dict error when request status code > 399
    * return -- formated error message   
    """
    # Add time stamp
    result["Time Stamp"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

    error_message = ""
    for key, value in result.items():
        if isinstance(value, list): 
            if value: value = value[0] 
            else: continue
        elif not value: continue
        
        error_message += "% 30s\t" % "{0}: ".format(key)
        value = urllib.parse.unquote(unescape(none_value(value), 
            {"&apos;": "'", "&quot;": '"'}))
        error_message += "%-30s\t" % value + "\n"

    return error_message[:len(error_message)-1]

def format_waiting_message(result, header=""):
    error_message = header + "\n" + "-" * 100 + "\n"
    for key in result:
        if isinstance(result[key], list): continue
        error_message += "% 30s\t" % "{0}: ".format(key)
        error_message += "%-30s\t" % none_value(result[key]) + "\n"

    if "messages" in result:
        messages = result["messages"]
        error_message += message.SEPRATE.format("Deploy Messages")
        for key in messages[0].keys():
            error_message += "%-30s" % key.capitalize()
        error_message += "\n"
        for msg in messages:
            for key in msg:
                error_message += "%-30s" % none_value(msg[key])
            error_message += "\n"

    return error_message

def format_xml(xml_string, indent="4"):
    """Return formatted XML string

    Arguments:

    * xml_string -- required parameter, not formatted XML string
    * indent     -- optional parameter, format indent

    Returns:

    * content    -- formatted XML string
    """

    try:
        formatter = xmlformatter.Formatter(indent=indent)
        content = formatter.format_string(xml_string)
    except:
        content = xml_string.encode("utf-8")

    return content

def none_value(value):
    """
    If value is None, return "", if not, return value

    @value: value
    """

    if not value: return ""
    return "%s" % value
    
def is_python3x():
    """
    If python version is 3.x, return True
    """

    return sys.version > '3'

"""
Below three functions are used to parse completions out of box.
"""
def parse_namespace(publicDeclarations):
    """
    from . import util
    import json
    namespace_json = util.parse_namespace(publicDeclarations["publicDeclarations"])
    json.dump(namespace_json, open("c:/namespace.json",'w'))
    """

    namespaces_dict = {}
    for namespace in publicDeclarations:
        namespaces_dict[namespace] = list(publicDeclarations[namespace].keys())

    return namespaces_dict

def parse_method(methods, is_method=True):
    if not methods: return {}

    methods_dict = {}
    for method in methods:
        if not method["name"]: continue
        if not is_method:
            returnType = ''
        else:
            returnType = method["returnType"]
        if not method["parameters"]:
            methods_dict["%s()\t%s" % (method["name"], returnType)] = method["name"] + "()$0"
        else:
            display_parameters = []
            for parameter in method["parameters"]:
                display_parameters.append(parameter["type"] + " " + parameter["name"])

            return_parameters = []
            for i in range(len(display_parameters)):
                return_parameters.append("${%s:%s}" % (i + 1, display_parameters[i]))

            methods_dict["%s(%s)\t%s" % (method["name"], ','.join(display_parameters), returnType)] =\
                "%s(%s)$0" % (method["name"], ','.join(return_parameters))

    return methods_dict

def parse_properties(properties):
    if not properties: return {}
    properties_dict = {}
    for property in properties:
        properties_dict[property["name"]] = property["name"] + "$0"

    return properties_dict

def parse_all(apex):
    """
    Usage:
        from . import util
        import json
        apex_json = util.parse_all(apex)


        from .salesforce.lib import apex
        return_apex = {}
        for lib in apex.apex_completions:
            if "customize" in apex.apex_completions[lib]:
                apex_json[lib] = apex.apex_completions[lib]

        json.dump(apex_json, open("/Users/mouse/apex.json",'w'))
    """

    apex_completions = {}
    for namespace in apex.keys():
        for class_name in apex[namespace]:
            class_detail = apex[namespace][class_name]

            constructors_dict = parse_method(class_detail["constructors"], False)
            methods_dict = parse_method(class_detail["methods"])
            properties_dict = parse_properties(class_detail["properties"])

            # all_dict = dict(list(methods_dict.items()) + list(properties_dict.items()))

            # Below class are duplicate in different namespace
            # Communities, TimeZone, UnsupportedOperationException, Test, QueryException, Action            
            if class_name.lower() in apex_completions:
                apex_completions[class_name.lower()] = [apex_completions[class_name.lower()]]
                apex_completions[class_name.lower()].append({
                    "constructors" : constructors_dict,
                    "methods" : methods_dict,
                    "properties" : properties_dict,
                    "namespace" : namespace,
                    "name": class_name
                })
            else:
                apex_completions[class_name.lower()] = {}
                apex_completions[class_name.lower()]["constructors"] = constructors_dict
                apex_completions[class_name.lower()]["methods"] = methods_dict
                apex_completions[class_name.lower()]["properties"] = properties_dict
                apex_completions[class_name.lower()]["namespace"] = namespace
                apex_completions[class_name.lower()]["name"] = class_name
            
    return apex_completions

def parse_code_coverage(result):
    records = {}
    for record in result["records"]:
        name = record["ApexClassOrTrigger"]["Name"]
        records[name] = {
            "NumLinesCovered" : record["NumLinesCovered"],
            "NumLinesUncovered": record["NumLinesUncovered"]
        }

    code_coverage_desc = message.SEPRATE.format("TriggerOrClass Code Coverage:")

    columns = ""
    header_width = {
        "Name": 50, "Percent": 10, "Lines": 10
    }
    for column in ["Name", "Percent", "Lines"]:
        columns += "%-*s" % (header_width[column], column)

    code_coverage = ""
    for name in sorted(records):
        row = ""
        row += "%-*s" % (header_width["Name"], name)
        coverage = records[name]
        if not coverage["NumLinesCovered"] or not coverage["NumLinesUncovered"]:
            continue
        covered_lines = coverage["NumLinesCovered"]
        total_lines = covered_lines + coverage["NumLinesUncovered"]
        coverage = covered_lines / total_lines * 100 if total_lines != 0 else 0
        row += "%-*s" % (header_width["Percent"], "%.2f%%" % coverage)
        row += "%-*s" % (header_width["Lines"], "%s/%s" % (covered_lines, total_lines))
        code_coverage += row + "\n"

    return message.SEPRATE.format(code_coverage_desc + columns + "\n"*2 + code_coverage)

def parse_test_result(test_result):
    """
    format test result as specified format

    * result: Run Test Request result
    * return: formated string
    """

    # Parse Test Result
    test_result_desc = ' Test Result\n'
    test_result_content = ""
    class_name = ""
    for record in test_result:
        test_result_content += "-" * 100 + "\n"
        test_result_content += "% 30s    " % "MethodName: "
        test_result_content += "%-30s" % none_value(record["MethodName"]) + "\n"
        test_result_content += "% 30s    " % "TestTimestamp: "
        test_result_content += "%-30s" % none_value(record["TestTimestamp"]) + "\n"
        test_result_content += "% 30s    " % "ApexClass: "
        class_name = record["ApexClass"]["Name"]
        test_result_content += "%-30s" % class_name + "\n"
        test_result_content += "% 30s    " % "Pass/Fail: "
        test_result_content += "%-30s" % none_value(record["Outcome"]) + "\n"
        test_result_content += "% 30s    " % "Error Message: "
        test_result_content += "%-30s" % none_value(record["Message"]) + "\n"
        test_result_content += "% 30s    " % "Stack Trace: "
        test_result_content += "%-30s" % none_value(record["StackTrace"]) + "\n"

    return_result = class_name + test_result_desc + test_result_content[:-1]

    # Parse Debug Log Part
    debug_log_desc = message.SEPRATE.format("You can choose the LogId and view log detail in Sublime or Salesforce by context menu")
    debug_log_content = "LogId: "
    if len(test_result) > 0 and test_result[0]["ApexLogId"] != None:
        debug_log_content += test_result[0]["ApexLogId"]

    return_result += debug_log_desc + debug_log_content

    return return_result

def parse_validation_rule(settings, sobjects):
    """ Parse the validation rule in Sobject.object to csv

    * settings -- toolingapi.sublime-settings reference
    * sobject -- sobject name
    * validation_rule_path -- downloaded objects path by Force.com IDE or ANT
    """

    # Open target file
    outputdir = settings["workspace"] + "/.export"
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    # Initiate CSV Writer and Write headers
    columns = settings["validation_rule_columns"]
    with open(outputdir + "/ValidationRules.csv", "wb") as fp:
        fp.write(u'\ufeff'.encode('utf8')) # Write BOM Header
        fp.write(",".join(columns).encode("utf-8") + b"\n") # Write Header

    # Open workflow source file
    validation_rule_path = settings["workspace"] + "/src/objects"
    for sobject in sobjects:
        try:
            with open(validation_rule_path + "/" + sobject + ".object", "rb") as f:
                result = xmltodict.parse(f.read())
        except IOError:
            # If one sobject is not exist, We don't need do anything
            continue

        ######################################
        # Rules Part
        ######################################
        try:
            rules = result["CustomObject"]["validationRules"]
            fp = open(outputdir + "/Validation Rules.csv", "ab")
            write_metadata_to_csv(fp, columns, rules, sobject)
        except KeyError:
            # If one sobject doesn't have vr, We don't need do anything
            pass

def parse_workflow_metadata(settings, sobjects):
    """Parse Sobject.workflow to csv, including rule, field update and alerts

    * settings -- toolingapi.sublime-settings reference
    * sobject -- sobject name
    * workflow_metadata_path -- downloaded workflow path by Force.com IDE or ANT
    """
    # Create workflow dir
    outputdir = settings["workspace"] + "/.export"
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    workflow_config = {
        "rules": {
            "file_name": "Workflow Rules",
            "setting_name": "workflow_rule_columns"
        },
        "fieldUpdates": {
            "file_name": "Workflow Field Updates",
            "setting_name": "workflow_field_update_columns"
        },
        "alerts": {
            "file_name": "Workflow Email Alerts",
            "setting_name": "workflow_email_alert_columns"
        },
        "outboundMessages": {
            "file_name": "Workflow Outbound Messages",
            "setting_name": "workflow_outbound_message_columns"
        },
        "tasks": {
            "file_name": "Workflow Tasks",
            "setting_name": "workflow_task_columns"
        }
    }

    for config in workflow_config:
        setting_name = workflow_config[config]["setting_name"]
        file_name = workflow_config[config]["file_name"]
        columns = settings[setting_name]
        rule_outputdir = outputdir + "/%s.csv" % file_name

        # If file is exist, just remove it
        if os.path.isfile(rule_outputdir):
            os.remove(rule_outputdir)

        # Write Header
        with open(rule_outputdir, "wb") as fp:
            fp.write(u'\ufeff'.encode('utf8')) # Write BOM Header
            fp.write(",".join(columns).encode("utf-8") + b"\n") # Write Header

        # Append Body
        rule_path = settings["workspace"] + "/src/workflows"
        for sobject in sobjects:
            try:
                with open(rule_path + "/" + sobject + ".workflow", "rb") as f:
                    result = xmltodict.parse(f.read())
            except IOError:
                # If one sobject is not exist, We don't need do anything
                continue

            try:
                rules = result["Workflow"][config]
                write_metadata_to_csv(open(rule_outputdir, "ab"), columns, rules, sobject)
            except KeyError:
                # If one sobject doesn't have vr, We don't need do anything
                pass

def write_metadata_to_csv(fp, columns, metadata, sobject):
    """ This method is invoked by function in this module

    Arguments:

    * fp -- output csv file open reference
    * columns -- your specified metadata workbook columns in settings file
    * metadata -- metadata describe
    """

    # If sobject has only one rule, it will be dict
    # so we need to convert it to list
    if isinstance(metadata, dict):
        metadata_temp = [metadata]
        metadata = metadata_temp

    columns = [col for col in columns if col != "sobject"]

    row_values = b""
    for rule in metadata:
        row_value = [sobject]
        for key in columns:
            # Because Workflow rule criteria has different type
            # If key is not in rule, just append ""
            if key not in rule.keys():
                row_value.append("")
                continue

            cell_value = rule[key]
            if isinstance(cell_value, list):
                value = ''
                if len(cell_value) > 0:
                    if isinstance(cell_value[0], dict):
                        values = []
                        for cell_dict in cell_value:
                            for cell_dict_key in cell_dict.keys():
                                if not cell_dict[cell_dict_key]:
                                    values.append("")
                                else:
                                    values.append(cell_dict[cell_dict_key])
                            value += " ".join(values) + "\n"
                    else:
                        value = " ".join(cell_value) + "\n"

                    cell_value = value[ : -1]
                else:
                    cell_value = ""

            elif isinstance(cell_value, dict):
                value = ''
                for cell_key in cell_value.keys():
                    if not cell_value[cell_key]:
                        value += cell_key + ": ' '" + "\n"
                    else:
                        value += cell_key + ": " + cell_value[cell_key] + "\n"

                cell_value = value[ : -1]

            elif not cell_value:
                cell_value = ""
            else:
                cell_value = "%s" % cell_value

            # Unescape special code to normal
            cell_value = urllib.parse.unquote(unescape(cell_value, 
                {"&apos;": "'", "&quot;": '"'}))

            # Append cell_value to list in order to write list to csv
            if '"' in cell_value:
                cell_value = '"%s"' % cell_value.replace('"', '""')
            else:
                cell_value = '"%s"' % cell_value
            row_value.append(cell_value)

        # Write row
        row_value_bin = ",".join(row_value)
        row_values += row_value_bin.encode("utf-8") + b"\n"

    fp.write(row_values) # Write Body
    fp.close()

NOT_INCLUDED_COLUMNS = ["urls", "attributes"]
def list2csv(file_path, records):
    """convert simple dict in list to csv

    Arguments:

    * records -- [{"1": 1}, {"2": 2}]
    """
    # If records size is 0, just return
    if len(records) == 0: return "No Elements"

    headers = [k.encode('utf-8') for k in records[0] if k not in NOT_INCLUDED_COLUMNS]
    with open(file_path, "wb") as fp:
        fp.write(b",".join(headers) + b"\n")
        for record in records:
            values = []
            for k in headers:
                strk = str(k, encoding="utf-8")
                if strk not in record:
                    values.append(b"")
                else:
                    values.append(('"%s"' % none_value(record[strk])).encode("utf-8"))
            fp.write(b",".join(values) + b"\n")

def parse_data_template(output_file_dir, result):
    """Parse the data template to csv by page layout

    Arguments:
    
    * output_file_dir -- output dir for parsed result
    * result -- page layout describe result
    """

    field_lables = []
    field_apis = []
    fields_required = []
    fields_type = []
    fields_picklist_labels = []
    fields_picklist_values = []
    for edit_layout_section in result["editLayoutSections"]:
        if isinstance(edit_layout_section["layoutRows"], list):
            layout_rows = edit_layout_section["layoutRows"]
        elif isinstance(edit_layout_section["layoutRows"], dict):
            layout_rows = [edit_layout_section["layoutRows"]]

        for layout_row in layout_rows:
            if isinstance(layout_row["layoutItems"], list):
                layout_items = layout_row["layoutItems"]
            elif isinstance(layout_row["layoutItems"], dict):
                layout_items = [layout_row["layoutItems"]]

            for layout_item in layout_items:
                if not layout_item["label"]: continue
                for layout_component in layout_item["layoutComponents"]:
                    # Some layout_component is blank
                    if "details" not in layout_component: continue

                    # Get field describe
                    details = layout_component["details"]

                    # If field type is AutoNumber, just skip
                    if details["autoNumber"]: continue

                    field_lables.append(details["label"])
                    field_apis.append(details["name"])
                    fields_required.append("Required" if layout_item["required"] else "")
                    fields_type.append(details["type"].capitalize())

                    picklist_labels = []
                    picklist_values = []
                    for picklist in details["picklistValues"]:
                        picklist_labels.append(picklist["label"])
                        picklist_values.append(picklist["value"])
                        
                    fields_picklist_labels.append('"%s"' % "\n".join(picklist_labels))
                    fields_picklist_values.append('"%s"' % "\n".join(picklist_values))

    # Write field_lables and field apis
    # Create new csv
    with open(output_file_dir, "wb") as fp:
        fp.write(u'\ufeff'.encode('utf8'))
        fp.write(",".join(field_lables).encode("utf-8") + b"\n")
        fp.write(",".join(field_apis).encode("utf-8") + b"\n")
        fp.write(",".join(fields_type).encode("utf-8") + b"\n")
        fp.write(",".join(fields_required).encode("utf-8") + b"\n")
        fp.write(",".join(fields_picklist_labels).encode("utf-8") + b"\n")
        fp.write(",".join(fields_picklist_values).encode("utf-8") + b"\n")

def parse_execute_anonymous_xml(result):
    """Return the formatted anonymous execute result

    Arguments:

    * result -- execute anonymous result, it's a xml
    * return -- formated string
    """

    compiled = result["compiled"]
    debugLog = result["debugLog"]

    view_result = ''
    if compiled == "true":
        view_result = debugLog
    elif compiled == "false":
        line = result["line"]
        column = result["column"]
        compileProblem = result["compileProblem"]
        view_result = compileProblem + " at line " + line +\
            " column " + column

    view_result = urllib.parse.unquote(unescape(view_result, 
        {"&apos;": "'", "&quot;": '"'}))

    return view_result

def generate_workbook(result, workspace, workbook_field_describe_columns):
    """ generate workbook for sobject according to user customized columns
    you can change the workbook_field_describe_columns in default settings

    Arguments:

    * result -- sobject describe result
    * workspace -- your specified workspace in toolingapi.sublime-settings
    * workflow_field_update_columns -- your specified workbook columns in toolingapi.sublime-settings
    """
    # Get sobject name
    sobject = result.get("name")

    # Get fields
    fields = result.get("fields")
    fields_key = workbook_field_describe_columns

    # If workbook path is not exist, just make it
    outputdir = workspace + "/.export/workbooks"
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    # Create new csv file for this workbook
    # fp = open(outputdir + "/" + sobject + ".csv", "wb", newline='')
    workbook_dir = outputdir + "/" + sobject + ".csv"
    
    #------------------------------------------------------------
    # Headers, all headers are capitalized
    #------------------------------------------------------------
    headers = [column.capitalize() for column in fields_key]

    # Write Header
    fp = open(workbook_dir, "wb")
    fp.write(u'\ufeff'.encode('utf8')) # Write BOM Header
    fp.write(",".join(headers).encode("utf-8") + b"\n") # Write Header

    #------------------------------------------------------------
    # Fields Part (All rows are sorted by field label)
    #------------------------------------------------------------
    fields = sorted(fields, key=lambda k : k['label'])
    for field in fields:
        row_value_literal = b""
        row_values = []

        # Check field type
        field_type = field["type"] if not field["calculatedFormula"] \
            else "Formula(%s)" % field["type"]

        for key in fields_key:
            # Get field value by field API(key)
            row_value = field.get(key)
            
            if isinstance(row_value, list):
                if key == "picklistValues":
                    value = ''
                    if len(row_value) > 0:
                        for item in row_value:
                            value += item.get("value") + "\n"
                        row_value = value
                    else:
                        row_value = ""
                elif key == "referenceTo":
                    if len(row_value) > 0:
                        row_value = row_value[0]
                    else:
                        row_value = ""
            elif not row_value:
                row_value = ""
            else:
                row_value = field_type if key == "type" else "%s" % row_value

            # Unescape special code to normal
            row_value = urllib.parse.unquote(unescape(row_value, 
                {"&apos;": "'", "&quot;": '"'}))

            # Append row_value to list in order to write list to csv
            if '"' in row_value:
                row_value = '"%s"' % row_value.replace('"', '""')
            else:
                row_value = '"%s"' % row_value
            row_values.append(row_value)

        # Write row
        row_value_literal += ",".join(row_values).encode("utf-8") + b"\n"
        fp.write(row_value_literal)

    # Close fp
    fp.close()

    # Display Success Message
    sublime.set_timeout(lambda:sublime.status_message(sobject + " workbook is generated"), 10)

    # Return outputdir
    return outputdir

record_keys = ["label", "name", "type", "length"]
record_key_width = {
    "label": 40, 
    "name": 40, 
    "type": 20, 
    "length": 7
}
recordtype_key_width = {
    "available": 10,
    "recordTypeId": 20,
    "name": 35,
    "defaultRecordTypeMapping": 15
}
childrelationship_key_width = {
    "field": 35,
    "relationshipName": 35,
    "childSObject": 30,
    "cascadeDelete": 12
}

seprate = 100 * "-" + "\n"
def parse_sobject_field_result(result):
    """According to sobject describe result, display record type information, 
    child sobjects information and the field information.

    Arguments:

    * result -- sobject describe information, it's a dict
    * return -- formated string including the three parts
    """

    # Get sobject name
    sobject = result.get("name")

    # View Name or Header
    view_result = sobject + " Describe:\n"

    #------------------------------------------------
    # Fields Part
    #------------------------------------------------
    # Output totalSize Part
    fields = result.get("fields")
    view_result += seprate
    view_result += "Total Fields: \t" + str(len(fields)) + "\n"
    view_result += seprate

    # Ouput Title and seprate line
    columns = ""
    for key in record_keys:
        key_width = record_key_width[key]
        columns += "%-*s" % (key_width, key.capitalize())

    view_result += columns + "\n"
    view_result += len(columns) * "-" + "\n"

    # Sort fields list by lable of every field
    fields = sorted(fields, key=lambda k : k['label'])

    # Output field values
    for record in fields:
        row = ""
        for key in record_keys:
            row_value = "Formula(%s)" % record.get(key) if key == "type" \
                and record["calculatedFormula"] else record.get(key)
                
            if not row_value:
                row_value = ""

            key_width = record_key_width[key]
            row_value = "%-*s" % (key_width, row_value)
            row += row_value

        view_result += row + "\n"
    view_result += "\n"

    #------------------------------------------------
    # Record Type Part
    #------------------------------------------------
    recordtypes = result.get("recordTypeInfos")
    view_result += seprate
    view_result += "Record Type Info: \t" + str(len(recordtypes)) + "\n"
    view_result += seprate

    # Get Record Type Info Columns
    recordtype_keys = []
    if len(recordtypes) > 0:
        recordtype_keys = recordtypes[0].keys()

    columns = ""
    for key in recordtype_keys:
        if not key in recordtype_key_width: continue
        key_width = recordtype_key_width[key]
        if key == "defaultRecordTypeMapping": key = "default"
        columns += "%-*s" % (key_width, key.capitalize())

    view_result += columns + "\n"
    view_result += len(columns) * "-" + "\n"

    for recordtype in recordtypes:
        row = ""
        for key in recordtype_keys:
            if key not in recordtype_key_width: continue
            
            # Get field value by field API
            # and convert it to str
            row_value = recordtype.get(key)
            if not row_value:
                row_value = ""

            key_width = recordtype_key_width[key]
            row_value = "%-*s" % (key_width, row_value)
            row += row_value
            
        view_result += row + "\n"

    view_result += "\n"

    #------------------------------------------------
    # Child Relationship
    #------------------------------------------------
    childRelationships = result.get("childRelationships")
    view_result += seprate
    view_result += "ChildRelationships Info: \t" + str(len(childRelationships)) + "\n"
    view_result += seprate

    # Get Record Type Info Columns
    childRelationships_keys = childrelationship_key_width.keys()
    columns = ""
    for key in childRelationships_keys:
        columns += "%-*s" % (30, key.capitalize())

    view_result += columns + "\n"
    view_result += len(columns) * "-" + "\n"

    for childRelationship in childRelationships:
        row = ""
        for key in childRelationships_keys:
            # Get field value by field API
            # and convert it to str
            row_value = childRelationship.get(key)
            if not row_value:
                row_value = ""

            row_value = "%-*s" % (30, row_value)
            row += row_value
            
        view_result += row + "\n"

    view_result += "\n"

    return view_result

def getUniqueElementValueFromXmlString(xmlString, elementName):
    """
    Extracts an element value from an XML string.
    
    For example, invoking 
    getUniqueElementValueFromXmlString('<?xml version="1.0" encoding="UTF-8"?><foo>bar</foo>', 'foo')
    should return the value 'bar'.
    """
    xmlStringAsDom = xml.dom.minidom.parseString(xmlString)
    elementsByName = xmlStringAsDom.getElementsByTagName(elementName)
    elementValue = None
    if len(elementsByName) > 0:
        elementValue = elementsByName[0].toxml().replace('<' +\
            elementName + '>','').replace('</' + elementName + '>','')
    return unescape(elementValue, {"&apos;": "'", "&quot;": '"'})

def get_response_error(response):
    content = response.content
    result = {"success": False}
    if response.status_code == 500:
        result["Error Code"] = getUniqueElementValueFromXmlString(content, "faultcode")
        result["Error Message"] = getUniqueElementValueFromXmlString(content, "faultstring")
    else:
        result["Error Code"] = getUniqueElementValueFromXmlString(content, "errorCode")
        result["Error Message"] = getUniqueElementValueFromXmlString(content, "message")
    return result

def get_path_attr(path_dir):
    """Return project name and component folder attribute

    Arguments:

    * path_dir -- full path of specified file

    Returns:

    * project_name -- project name of default project
    * folder -- folder describe defined in settings, for example, ApexClass foder is 'src/classes'
    """
    # Get the Folder Name and Project Name
    path, metadata_folder = os.path.split(path_dir)
    path, src = os.path.split(path)
    path, project_name = os.path.split(path)

    # Assume the project name has time suffix, 
    year = get_current_year()
    if year in project_name: project_name = project_name[:-9]

    return project_name, metadata_folder

def get_current_year():
    """Get the current year

    Returns:

    * year -- year literal in current time
    """
    return time.strftime("%Y", time.localtime())

def get_file_attr(file_name):
    try:
        folder, extension = os.path.splitext(file_name)
        name = ""
        if "\\" in folder:
            name = folder[folder.rfind("\\")+1:]
        elif "/" in folder:
            name = folder[folder.rfind("/")+1:]
        return name, extension
    except:
        pass

def get_meta_folder(file_name):
    """ Get the meta_folder by file_name

    * file_name -- Local component full file name, for example:
        if file name is "/pro-exercise-20130625/src/classes/AccountChartController.cls",
        the meta_folder is "classes"

    Returns: 

    * metadata_folder -- the metadata folder
    """

    return get_folder_and_name(file_name)[0]

def get_folder_and_name(file_name):
    folder, name = os.path.split(file_name)
    src_folder, metadata_folder = os.path.split(folder)
    name, extension = name.split(".")

    return (metadata_folder, name)

def get_component_attribute(file_name):
    """
    get the component name by file_name, and then get the component_url and component_id
    by component name and local settings

    Arguments:

    * file_name -- Local component full file name, for example:
        /pro-exercise-20130625/src/classes/AccountChartController.cls

    Returns: 

    * (component_attribute, file name) -- for example, component_attribute = {
        "body": "Body",
        "extension": ".cls",
        "id": "01pO00000009isEIAQ",
        "is_test": false,
        "type": "ApexClass",
        "url": "/services/data/v28.0/sobjects/ApexClass/01pO00000009isEIAQ"
    }
    """
    # Get toolingapi settings
    settings = context.get_settings()

    # Check whether current file is subscribed component
    folder, name = os.path.split(file_name)
    component_name = name.split(".")[0]
    src_folder, metadata_folder = os.path.split(folder)
    if metadata_folder not in settings["metadata_folders"]:
        return None, None

    xml_name = settings[metadata_folder]["xmlName"]
    username = settings["username"]
    component_settings = sublime.load_settings(context.COMPONENT_METADATA_SETTINGS)

    try:
        component_attribute = component_settings.get(username)[xml_name][component_name.lower()]
    except:
        component_attribute, component_name = None, None

    # Return tuple
    return (component_attribute, component_name)

def check_enabled(file_name, check_cache=True):
    """
    Check whether file is ApexTrigger, ApexComponent, ApexPage or ApexClass

    Arguments:

    * file_name -- file name in context

    Returns:

    * Bool -- check whether current file is apex code file and has local cache
    """
    if not file_name: return False

    # Get toolingapi settings
    settings = context.get_settings()

    # Check whether current file is subscribed component
    folder, name = os.path.split(file_name)
    src_folder, folder_name = os.path.split(folder)
    if folder_name not in settings["metadata_folders"]: 
        sublime.status_message("Not valid SFDC component")
        return False

    # Check whether project of current file is active project
    default_project_name = settings["default_project_name"]
    if not default_project_name.lower() in file_name.lower(): 
        sublime.status_message('This project is not active project');
        return False

    # Check whether active component is in active project
    if check_cache:
        username = settings["username"]
        component_attribute, component_name = get_component_attribute(file_name)
        if not component_attribute: 
            sublime.status_message("This component is not active component")
            return False
    
    return True

def display_active_project(view):
    """ Display the default project name in the sidebar
    """

    settings = context.get_settings()
    display_message = "Default Project => " + settings["default_project_name"]
    view.set_status('default_project', display_message)

def switch_project(chosen_project):
    """ Set the default project to the chosen one
    """

    s = sublime.load_settings(context.TOOLING_API_SETTINGS)
    projects = s.get("projects")

    # Set the chosen project as default and others as not default
    for project in projects:
        project_attr = projects[project]
        if chosen_project == project:
            project_attr["default"] = True
        else:
            project_attr["default"] = False

    # Save the updated settings
    s.set("projects", projects)
    sublime.save_settings(context.TOOLING_API_SETTINGS)

    # Set status of all views in all window with "default project"
    for window in sublime.windows():
        for view in window.views():
            display_active_project(view)

def add_project_to_workspace(settings):
    """Add new project folder to workspace
       Just Sublime Text 3 can support this method
    """

    # Just ST3 supports, ST2 is not
    workspace = settings["workspace"]
    file_exclude_patterns = settings["file_exclude_patterns"]
    folder_exclude_patterns = settings["folder_exclude_patterns"]
    project_data = sublime.active_window().project_data()
    if not project_data: project_data = {}
    folders = []
    if "folders" in project_data:
        folders = project_data["folders"]

    # If the workspace is already exist in project data,
    # just update the patters, if not, add the workspace to it
    for folder in folders:
        # Parse windows path to AS-UNIX
        if "\\" in folder : folder = folder.replace("\\", "/")
        if "\\" in workspace : workspace = workspace.replace("\\", "/")

        if folder["path"] == workspace:
            folder["file_exclude_patterns"] = file_exclude_patterns;
            folder["folder_exclude_patterns"] = folder_exclude_patterns
        else:
            folders.append({
                "path": workspace,
                "file_exclude_patterns": file_exclude_patterns,
                "folder_exclude_patterns": folder_exclude_patterns
            })
    else:
        folders.append({
            "path": workspace,
            "file_exclude_patterns": file_exclude_patterns,
            "folder_exclude_patterns": folder_exclude_patterns
        })

    project_data["folders"] = folders
    sublime.active_window().set_project_data(project_data)

def get_metadata_elements(metadata_dir):
    """ Get the name list by specified metadataObject

    Arguments:

    metadata_dir -- directory of metadataObject

    Return:

    names -- elements in the specified metadataObject folder
    """

    
    elements = []
    for parent, dirnames, filenames in os.walk(metadata_dir):
        for _file in filenames:
            if _file.endswith("-meta.xml"): continue
            base, name = os.path.split(_file)
            name, extension = name.split(".")
            elements.append(name)

    return elements

def export_profile_settings():
    settings = context.get_settings()

    # Read all profile names
    profile_dir = os.path.join(settings["workspace"], "src", "profiles")
    if not os.path.exists(profile_dir):
        Printer.get("error").write("Profiles directory can not be found, please execute `retrieve all` command")
        return

    Printer.get("log").write_start().write("Start to read all file name in profile folder")
    profiles = get_metadata_elements(profile_dir)

    profile_settings = {}
    sobject_names = []
    tab_names = []
    permission_names = []
    for profile in profiles:
        # Escape profile name, for example, 
        # "Custom%3A Sales Profile" changed to "Custom: Sales Profile"
        unquoted_profile = urllib.parse.unquote(unescape(profile, {"&apos;": "'", "&quot;": '"'}))
        Printer.get("log").write("Parsing the profile security settings of "+unquoted_profile)

        profile_file = os.path.join(profile_dir, profile+".profile")
        result = xmltodict.parse(open(profile_file, "rb").read())
        result = result["Profile"]

        profile_settings[unquoted_profile] = {}

        # Some profiles don't have objectPermissions
        if "objectPermissions" in result:
            sobjects_permission = {}

            object_permissions = result["objectPermissions"]

            # Some profiles just only have one objectPermissions
            if isinstance(result["objectPermissions"], dict): 
                object_permissions = [object_permissions]

            for op in object_permissions:
                sobjects_permission[op["object"]] = op
                if op["object"] not in sobject_names:
                    sobject_names.append(op["object"])

            profile_settings[unquoted_profile]["objectPermissions"] = sobjects_permission

        # Parsing tabVisibilities as {}
        if "recordTypeVisibilities" in result:
            pass

        # Parsing tabVisibilities as {"tabName1": "visibility", "tabName2": "Visibility"}
        if "tabVisibilities" in result:
            tab_visibilities = {}

            # Some profiles just only have one tabVisibilities
            tvs = result["tabVisibilities"]
            if isinstance(tvs, dict): tvs = [tvs]

            for tv in tvs:
                tab_visibilities[tv["tab"]] = tv["visibility"]
                if tv["tab"] not in tab_names:
                    tab_names.append(tv["tab"])
            profile_settings[unquoted_profile]["tabVisibilities"] = tab_visibilities

        # Parsing userPermissions as {"ApiEnabled": true, ""AllowUniversalSearch"": false}
        if "userPermissions" in result:
            user_permissions = {}

            # Some profiles just only have one userPermissions
            ups = result["userPermissions"]
            if isinstance(ups, dict): ups = [ups]

            for up in ups:
                user_permissions[up["name"]] = up["enabled"]
                if up["name"] not in permission_names:
                    permission_names.append(up["name"])
            profile_settings[unquoted_profile]["userPermissions"] = user_permissions

    # Get the unescaped profiles
    profiles = sorted(list(profile_settings.keys()))
    
    #########################################
    # 1. Export objectPermissions
    #########################################
    # Define object CRUD
    cruds = [
        "allowRead", "allowCreate", "allowEdit", 
        "allowDelete", "modifyAllRecords", 
        "viewAllRecords"
    ]

    cruds_translation = {
        "allowRead": "Read", 
        "allowCreate": "Create", 
        "allowEdit": "Edit", 
        "allowDelete": "Delete", 
        "modifyAllRecords": "ModifyAll", 
        "viewAllRecords": "ViewAll"
    }

    # Define the column that contains profile
    Printer.get("log").write("Generating csv content for profile object security")
    profile_headers = ["Object"]
    for profile in profiles:
        profile_headers.append(profile)
        for i in range(len(cruds) - 1):
            profile_headers.append("")

    # Define the column
    crud_headers = [""]
    for profile in profiles:
        for crud in cruds:
            crud_headers.append(cruds_translation[crud])

    sobject_names = sorted(sobject_names)
    all_rows = [",".join(profile_headers), ",".join(crud_headers)]
    for sobject in sobject_names:
        rows = [sobject]
        for profile in profiles:
            # Some standard sObject is not configurable
            if "objectPermissions" in profile_settings[profile]:
                if sobject in profile_settings[profile]["objectPermissions"]:
                    object_permission = profile_settings[profile]["objectPermissions"][sobject]
                    for crud in cruds:
                        rows.append("√" if object_permission[crud] == "true" else "x")
                else:
                    for crud in cruds:
                        rows.append("x")
            else:
                for crud in cruds:
                    rows.append("x")

        all_rows.append(",".join(rows))

    outputdir = settings["workspace"]+ "/.export/profile"
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    Printer.get("log").write("Writing profile object security to "+outputdir)
    with open(outputdir+"/ObjectPermissions.csv", "wb") as fp:
        fp.write("\n".join(all_rows).encode("utf-8"))

    #########################################
    # 2. Export tabVisibilities
    #########################################
    # Populate Header
    headers = ["Tab Name"]
    headers.extend(profiles)

    # Populate Rows
    tab_names = sorted(tab_names)
    all_rows = [",".join(headers)]
    for tab_name in tab_names:
        rows = [tab_name]
        for profile in profiles:
            if "tabVisibilities" in profile_settings[profile]:
                if tab_name in profile_settings[profile]["tabVisibilities"]:
                    rows.append(profile_settings[profile]["tabVisibilities"][tab_name])
                else:
                    rows.append("TabHidden")
            else:
                rows.append("No Tab Permission")

        all_rows.append(",".join(rows))

    Printer.get("log").write("Writing profile tab visibility to "+outputdir)
    with open(outputdir+"/TabVisibilities.csv", "wb") as fp:
        fp.write("\n".join(all_rows).encode("utf-8"))

    #########################################
    # 3. Export tabVisibilities
    #########################################
    # Populate Header
    headers = ["Permission"]
    headers.extend(profiles)

    # Populate Rows
    all_rows = [",".join(headers)]
    permission_names = sorted(permission_names)
    for permission_name in permission_names:
        rows = [permission_name]
        for profile in profiles:
            if permission_name in profile_settings[profile]["userPermissions"]:
                if profile_settings[profile]["userPermissions"][permission_name] == "true":
                    rows.append("√")
                else:
                    rows.append("x")
            else:
                rows.append("x")

        all_rows.append(",".join(rows))

    Printer.get("log").write("Writing profile user permission to "+outputdir)
    with open(outputdir+"/UserPermissions.csv", "wb") as fp:
        fp.write("\n".join(all_rows).encode("utf-8"))
