import json
import os
from . import config
from datetime import datetime

def generate():
    """Responsible for generating the resources pages"""
    generate_markdown_files()
    generate_faq_page()

def generate_markdown_files():
    """Responsible for compiling resources json into resources markdown files
       for rendering on the HMTL
    """
    # load papers and presentations list
    with open(os.path.join(config.data_directory, "resources.json"), "r") as f:
        resources = json.load(f)
    
    # get papers and presentations in sorted date order
    papers = sorted(resources["papers"], key=lambda p: datetime.strptime(p["date"], "%B %Y"), reverse=True)
    presentations = sorted(resources["presentations"], key=lambda p: datetime.strptime(p["date"], "%B %Y"), reverse=True)
    # get markdown
    resources_content = config.resources_md + json.dumps({
        "papers": papers,
        "presentations": presentations
    })
    # write markdown to file
    with open(os.path.join(config.resources_markdown_path, "resources.md"), "w", encoding='utf8') as md_file:
        md_file.write(resources_content)

def generate_faq_page():
    """Responsible for compiling faq json into faq markdown file
       for rendering on the HMTL
    """
    # load faq data from json
    with open(os.path.join(config.data_directory, "faq.json"), "r") as f:
        faqdata = json.load(f)
    # add unique IDs
    for i,section in enumerate(faqdata["sections"]):
        for j,item in enumerate(section["questions"]):
            item["id"] = f"faq-{i}-{j}"
    
    # get markdown
    faq_content = config.faq_md + json.dumps(faqdata)
    # write markdown to file
    with open(os.path.join(config.resources_markdown_path, "faq.md"), "w", encoding='utf8') as md_file:
        md_file.write(faq_content)
