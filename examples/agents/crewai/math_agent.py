# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import crew
from langchain_community.tools import tool
from crewai.tools import tool
from crewai.agents.parser import AgentAction, AgentFinish
from crewai.agents.crew_agent_executor import ToolResult


def step_callback(step):
    if isinstance(step, AgentAction):
        print(f">>> Action: {step.text} <<<")
    elif isinstance(step, AgentFinish):
        print(f">>> Finish: {step.text} <<<")
    elif isinstance(step, ToolResult):
        print(f">>> Tool Result: {step.result} <<<")


@tool("Add")
def add(a: int, b: int) -> int:
    """Adds a and b.

    Args:
        a: first int
        b: second int
    """
    return a + b


@tool("Multiply")
def multiply(a: int, b: int) -> int:
    """Multiplies a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b


@tool("Divide")
def divide(a: int, b: int) -> float:
    """Divide a and b.

    Args:
        a: first int
        b: second int
    """
    return a / b


class MathAgent:
    def __init__(self, model, base_url, step_callback):
        self.model = model
        self.base_url = base_url
        self.step_callback = step_callback

        # Initializing LLM with provided model and base_url
        self.llm = LLM(model=self.model, base_url=self.base_url)

        # Creating the Math Agent
        self.math_agent = Agent(
            role="Math Wizard",
            goal="use the calculator tool to do math",
            backstory="has done many calculations before",
            verbose=True,
            allow_delegation=True,
            llm=self.llm,
        )

        # Defining the Math Task
        self.math_task = Task(
            description="{prompt}",
            expected_output="Result of the mathematical expression",
            agent=self.math_agent,
            tools=[add, multiply, divide],
            verbose=True,
            allow_delegation=True,
            llm=self.llm,
        )

        # Setting up the Crew
        self.crew = Crew(
            agents=[self.math_agent],
            tasks=[self.math_task],
            process=Process.sequential,
            verbose=True,
            step_callback=self.step_callback,
        )

    def getCrew(self) -> Crew:
        return self.crew
