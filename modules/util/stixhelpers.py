import json
import os
import requests
import stix2
import urllib3
from modules import site_config
from . import buildhelpers
import time

def get_mitigation_list(src):
    """Reads the STIX and returns a list of all mitigations in the STIX"""

    mitigations = src.query([
        stix2.Filter('type', '=', 'course-of-action'),
        stix2.Filter('revoked', '=', False)
    ])

    #Filter out deprecated objects for mitigation pages
    mitigations = [x for x in mitigations if not hasattr(x, 'x_mitre_deprecated') or x.x_mitre_deprecated == False]
    
    return sorted(mitigations, key=lambda k: k['name'].lower())

def get_matrices(src):
    """Reads the STIX and returns a list of all matrices in the STIX"""

    matrices = src.query([
        stix2.Filter('type', '=', 'x-mitre-matrix'),
    ])

    return matrices

def get_tactic_list(src, matrix_id=None):
    """Reads the STIX and returns a list of all tactics in the STIX"""

    tactics = []
    matrix = src.query([
        stix2.Filter('type', '=', 'x-mitre-matrix'),
    ])

    if matrix_id:
        for curr_matrix in matrix:
            if curr_matrix['id'] == matrix_id:
                for tactic_id in curr_matrix['tactic_refs']:
                    tactics.append(src.query([stix2.Filter('id', '=', tactic_id)])[0])    
    else:
        for i in range(len(matrix)):
            for tactic_id in matrix[i]['tactic_refs']:
                tactics.append(src.query([stix2.Filter('id', '=', tactic_id)])[0])    
    
    return tactics

def get_all_of_type(src, obj_type):
    """Reads the STIX and returns a list of all of a particular
       type of object in the STIX
    """

    return src.query([stix2.Filter('type', '=', obj_type)])

def get_techniques(src):
    """Reads the STIX and returns a list of all techniques in the STIX"""

    tech_list = src.query([
        stix2.Filter('type', '=', 'attack-pattern'),
        stix2.Filter('revoked', '=', False)
    ])

    tech_list = sorted(tech_list, key=lambda k: k['name'].lower())
    return tech_list

def get_revoked_by(stix_id, src):
    """Given a stix_id, return an object that revokes it,
       if no object is found, return None
    """

    relations = src.relationships(stix_id, 'revoked-by', source_only=True)
    revoked_by = src.query([
        stix2.Filter('id', 'in', [r.target_ref for r in relations]),
        stix2.Filter('revoked', '=', False)
    ])
    if revoked_by:
        try:
            revoked_by = revoked_by[0]
        except IndexError:
            print("Malformed STIX content detected")
            print(stix_id)
            revoked_by = revoked_by[0]
    return revoked_by

def get_examples(tech_stix_id, src):
    """Given a technique stix id, return a list of examples with their 
       external references.
    """

    examples = []
    ext_refs = []
    for r in src.relationships(tech_stix_id, 'uses', target_only=True):
        if stix2.utils.get_type_from_id(r.source_ref) in ['intrusion-set', 'tool', 'malware']:
            curr_refs = None
            attack_id = None
            if 'external_references' in r:
                curr_refs = r.external_references
            example = src.query([
                stix2.Filter('id', '=', r.source_ref), 
                stix2.Filter('revoked', '=', False)
            ])[0]
            attack_id = buildhelpers.get_attack_id(example)
            examples.append({'name': example.name, 
                             'id': attack_id, 
                             'description': r.description, 
                             'ext_refs': curr_refs})
    
    examples = sorted(examples, key=lambda k: k['name'].lower())
    for example in examples:
        if example['ext_refs']:
            ext_refs += example['ext_refs']

    return examples, ext_refs

def get_technique_id_domain_map(ms):
    """Create map from technique_id to domain"""
    
    tech_list = {}

    for domain in site_config.domains:
        if domain['deprecated']: continue
        curr_list = ms[domain['name']].query([
            stix2.Filter('type', '=', 'attack-pattern'),
            stix2.Filter('revoked', '=', False)
        ])
        for val in curr_list:
            technique_id = buildhelpers.get_attack_id(val)
            if technique_id:
                tech_list[technique_id] = domain['name']
    
    return tech_list

def add_replace_or_ignore(stix_objs, attack_id_objs, obj_in_question):
    """ Add if object does not already exist
        Replace object if exist depending on deprecation status or modified date
        Ignore if object already exists but object in question is outdated

        Deconflicts objects by ATT&CK and STIX IDs
    """

    def has_STIX_ATTACK_ID_conflict(attack_id):
        # Check if STIX ID has been seen before, if it has, return ATT&CK ID of conflict ATT&CK if ATT&CK IDs are different
        conflict = stix_objs.get(obj_in_question.id)
        if conflict:
            conflict_attack_id = buildhelpers.get_attack_id(conflict)
            if conflict_attack_id != attack_id and attack_id_objs.get(conflict_attack_id):
                return conflict_attack_id
        
        return None
    
    def replace_object(attack_id, conflict_attack_id):
        # Replaces object on ATT&CK and STIX maps
        # Verify for STIX to ATT&CK conflict
        if conflict_attack_id:
            attack_id_objs[attack_id] = obj_in_question
            # Remove outdated ATT&CK ID from map
            attack_id_objs.pop(conflict_attack_id)
        else:
            attack_id_objs[attack_id] = obj_in_question

        stix_objs[obj_in_question.id] = obj_in_question

    # Get ATT&CK ID
    attack_id = buildhelpers.get_attack_id(obj_in_question)

    if not attack_id:
        # Ignore if ATT&CK ID does not exist
        return

    # Get ATT&CK ID if there is possible conflict with STIX ID and ATT&CK ID
    conflict_attack_id = has_STIX_ATTACK_ID_conflict(attack_id)

    # Check if object in conflict exists
    # STIX ID
    stix_id_obj_in_conflict = stix_objs.get(obj_in_question.id)

    # Get ATT&CK ID conflicts
    if conflict_attack_id:
        attack_id_obj_in_conflict = attack_id_objs.get(conflict_attack_id)
    else:
        attack_id_obj_in_conflict = attack_id_objs.get(attack_id)

    # ------------------------------------------------------------------------
    # Add: Object does not exist

    if not stix_id_obj_in_conflict:
        # Add if object does not exist in STIX ID map
        stix_objs[obj_in_question.id] = obj_in_question

    if not attack_id_obj_in_conflict:
        # Add if object does not exist in ATT&CK ID map
        attack_id_objs[attack_id] = obj_in_question

    # ------------------------------------------------------------------------
    # Replace: Object already exists

    # Ignore if object in question is deprecated and object in conflict is not
    elif not attack_id_obj_in_conflict.get('x_mitre_deprecated') and obj_in_question.get('x_mitre_deprecated'):
        return

    # If object in conflict is deprecated and recent object is not, select recent
    elif attack_id_obj_in_conflict.get('x_mitre_deprecated') and not obj_in_question.get('x_mitre_deprecated'):
        # Replace object in conflict with object in question
        replace_object(attack_id, conflict_attack_id)

    # Replace if modified date is more recent
    else:
        conflict_modified = attack_id_obj_in_conflict.get('modified')
        in_question_modified = obj_in_question.get('modified')

        if in_question_modified > conflict_modified:
            # Replace object in conflict with object in question
            replace_object(attack_id, conflict_attack_id)
    
def grab_resources(ms):
    """Returns a dict that contains lists for the software, group,
       technique and mitigation objects.
    """

    def get_domain_resources(types):
        # Returns sorted list by name of domain resources by given type list
        # Builds list from unique ATT&CK IDs

        def grab_filtered_list_by_type(domain, stix_type):
            return ms[domain['name']].query([
                stix2.Filter('type', '=', stix_type),
                stix2.Filter('revoked', '=', False)
            ])

        # Track objects by STIX ID
        stix_objs = {}
        # Track objects by ATT&CK ID
        attack_id_objs = {}
        for domain in site_config.domains:
            if domain['deprecated']: continue

            for stix_type in types:
                curr_list = grab_filtered_list_by_type(domain, stix_type)

                for val in curr_list:
                    add_replace_or_ignore(stix_objs, attack_id_objs, val)

        # Convert into list of values
        resource_list = [attack_id_objs[key] for key in attack_id_objs]
        return sorted(resource_list, key=lambda k: k['name'].lower())

    #Generates the list of techniques
    tech_list = get_domain_resources(['attack-pattern'])

    #Generates list of software
    software_list = get_domain_resources(['malware', 'tool'])

    #Generates list of groups
    group_list = get_domain_resources(['intrusion-set'])

    #Generates a list of CoA
    coa_list = get_domain_resources(['course-of-action'])

    #Generates list of relationships
    rel_list = []
    for domain in site_config.domains:
        if domain['deprecated']: continue
        curr_list = ms[domain['name']].query([
            stix2.Filter('type', '=', 'relationship'),
        ])
        rel_list = rel_list + curr_list
    resources = {
        "relationships": rel_list, 
        "groups": group_list, 
        "software": software_list, 
        "techniques": tech_list, 
        "mitigations": coa_list
    }
    return resources

def get_stix_memory_stores():
    """This function reads the json files for each domain and creates a dict
       that contains the memory stores for each domain.
    """

    # suppress InsecureRequestWarning: Unverified HTTPS request is being made
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    ms = {}
    srcs = []

    # Set proxy
    proxy  = ""
    if site_config.args.proxy:
        proxy = site_config.args.proxy
    proxyDict = { 
        "http"  : proxy,
        "https" : proxy
    }

    for domain in site_config.domains:

        # Download json from http or https
        if domain['location'].startswith("http"):
            stix_json = requests.get(domain['location'], verify=False, proxies=proxyDict)
            if stix_json.status_code == 200:
                stix_json = stix_json.json()
                ms[domain['name']] = stix2.MemoryStore(stix_data=stix_json['objects'])
            elif stix_json.status_code == 404:
                exit(f"\n{domain['location']} stix bundle was not found")
            else:
                exit(f"\n{domain['location']} stix bundle download was unsuccessful")
        else:
            if os.path.exists(domain['location']):
                ms[domain['name']] = stix2.MemoryStore()
                ms[domain['name']].load_from_file(domain['location'])
            else:
                exit(f"\n{domain['location']} local file does not exist. If you intended a URL, please include http:// or https://")
        
        if not domain['deprecated']:
            srcs.append(ms[domain['name']])

    return ms, srcs

def get_contributors(ms):
    """Gets all contributors in the STIX content"""

    # contributors not in STIX are stored here:
    contributors = [
        'Craig Aitchison',
        'Elly Searle, CrowdStrike — contributed to tactic definitions'
    ]

    for domain in site_config.domains:
        if domain['deprecated']: continue
        obj_types = ['attack-pattern', 'malware', 'tool', 'intrusion-set']
        src = ms[domain['name']]
        obj_list = []
        for curr_type in obj_types:
            obj_list += src.query([
                stix2.Filter('type', '=', curr_type)
            ])

        for obj in obj_list:
            if 'x_mitre_contributors' in obj:
                contributors += obj['x_mitre_contributors']
    contributors = list(set(contributors))
    
    return sorted(contributors, key=lambda k: k.lower())