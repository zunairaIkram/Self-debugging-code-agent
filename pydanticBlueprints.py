from pydantic import BaseModel, Field
from typing import Any, Optional

class testCodeArgs(BaseModel):
    codeBlock:str = Field(description="The code generated for the specific coding problem.")

class TestCase(BaseModel):
    args:dict[str, Any] = Field(description="The inputs a code needs in order to execute")
    expected:Any = Field(description="Based on the input what response is expected from the code.")

class Plan(BaseModel):
    pseudocode:str = Field(description="The pseudocode steps of the user's given coding problem.")
    testCases:list["TestCase"]= Field(description="The test cases and edge cases for the coding problem in order to test it's response.")
    function_name:str = Field(description="Name of the function to call when testing")

class Critics(BaseModel):
    flaws:Optional[list[str]]=Field(default=None,description="Contains the list of flaws in the plan, can be None")